#![cfg(windows)]
use shikigen_desktop_lib::{
    backend::{BackendManager, BackendSnapshot, LaunchPlan},
    process::{self, SpawnSpec},
};
use std::{
    fs::File,
    io::{self, Write},
    os::windows::io::FromRawHandle,
    path::PathBuf,
    sync::{Arc, Mutex},
    thread,
    time::{Duration, Instant},
};

fn wait_for(manager: &BackendManager, state: &str) -> BackendSnapshot {
    let deadline = Instant::now() + Duration::from_secs(10);
    loop {
        let snapshot = manager.snapshot();
        if snapshot.state == state {
            return snapshot;
        }
        assert!(Instant::now() < deadline, "{snapshot:?}");
        thread::sleep(Duration::from_millis(10));
    }
}

fn stub(spec: &SpawnSpec, mode: &str) -> std::io::Result<Box<dyn process::ManagedProcess>> {
    let mut args = spec.args.clone();
    args.splice(
        0..2,
        [PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("tests/fixtures/backend_stub.py")
            .into_os_string()],
    );
    process::spawn(&SpawnSpec {
        executable: spec.executable.clone(),
        cwd: spec.cwd.clone(),
        args,
        env: vec![("BACKEND_TEST_MODE".into(), mode.into())],
    })
}

#[test]
fn recent_mebibyte_is_queryable_and_bad_utf8_does_not_break_shutdown() {
    let mut plan = LaunchPlan::development().unwrap();
    plan.config.startup_timeout_seconds = 8.0;
    plan.config.shutdown_timeout_seconds = 0.5;
    let manager = BackendManager::start(
        Arc::new(move || Ok(plan.clone())),
        Arc::new(|spec| stub(spec, "log_tail")),
        Arc::new(|_| {}),
    );
    let ready = wait_for(&manager, "ready");
    let logs = manager.logs();
    assert_eq!(logs.startup_id, ready.startup_id);
    assert_eq!(logs.retained_bytes, 1_048_576);
    assert!(logs.truncated);
    assert!(logs.read_error.is_none());
    assert_eq!(
        logs.text,
        format!("\u{fffd}{}\u{fffd}", "x".repeat(1_048_574))
    );
    manager.request_shutdown();
    wait_for(&manager, "stopped");
}

// Only the OS stderr endpoint is substituted; ownership and other pipes remain real.
struct WithStderr {
    child: Box<dyn process::ManagedProcess>,
    stderr: Option<File>,
}
impl process::ManagedProcess for WithStderr {
    fn take_stdio(&mut self) -> Option<process::Stdio> {
        let mut streams = self.child.take_stdio()?;
        streams.stderr = self.stderr.take()?;
        Some(streams)
    }
    fn wait_exit(&self, timeout: Duration) -> io::Result<Option<u32>> {
        self.child.wait_exit(timeout)
    }
    fn terminate_tree(&self) -> io::Result<()> {
        self.child.terminate_tree()
    }
    fn wait_tree_empty(&self, timeout: Duration) -> io::Result<bool> {
        self.child.wait_tree_empty(timeout)
    }
}
fn pipe() -> (File, File) {
    let (mut read, mut write) = (std::ptr::null_mut(), std::ptr::null_mut());
    unsafe {
        assert_ne!(
            windows_sys::Win32::System::Pipes::CreatePipe(
                &mut read,
                &mut write,
                std::ptr::null(),
                0
            ),
            0
        );
        (File::from_raw_handle(read), File::from_raw_handle(write))
    }
}
fn start(launcher: shikigen_desktop_lib::backend::Launcher) -> Arc<BackendManager> {
    let mut plan = LaunchPlan::development().unwrap();
    plan.config.startup_timeout_seconds = 8.0;
    plan.config.shutdown_timeout_seconds = 0.1;
    BackendManager::start(
        Arc::new(move || Ok(plan.clone())),
        launcher,
        Arc::new(|_| {}),
    )
}
fn wait_logs(
    manager: &BackendManager,
    predicate: impl Fn(&shikigen_desktop_lib::backend::BackendLogs) -> bool,
) {
    let deadline = Instant::now() + Duration::from_secs(5);
    loop {
        if predicate(&manager.logs()) {
            return;
        }
        assert!(Instant::now() < deadline);
        thread::sleep(Duration::from_millis(10));
    }
}

#[test]
fn retry_discards_old_logs_even_when_the_old_pipe_delivers_after_reclamation() {
    let (old_read, mut old_write) = pipe();
    let (new_read, mut new_write) = pipe();
    let readers = Mutex::new(vec![new_read, old_read]);
    let manager = start(Arc::new(move |spec| {
        let mut readers = readers.lock().unwrap();
        Ok(Box::new(WithStderr {
            child: stub(
                spec,
                if readers.len() == 2 {
                    "startup_error"
                } else {
                    "ready"
                },
            )?,
            stderr: readers.pop(),
        }))
    }));
    old_write.write_all(b"old-before-retry").unwrap();
    let failed = wait_for(&manager, "failed");
    wait_logs(&manager, |logs| logs.text == "old-before-retry");
    let accepted = manager.retry();
    assert!(accepted.accepted);
    assert_eq!(manager.logs().text, "");
    assert_eq!(manager.logs().startup_id, accepted.snapshot.startup_id);
    assert_ne!(accepted.snapshot.startup_id, failed.startup_id);
    // More than a pipe buffer: proves the old reader is still draining after retry.
    old_write.write_all(&b"old-late".repeat(20_000)).unwrap();
    new_write.write_all(b"new-only").unwrap();
    wait_for(&manager, "ready");
    wait_logs(&manager, |logs| logs.text == "new-only");
    assert_eq!(manager.logs().retained_bytes, 8);
    manager.request_shutdown();
    wait_for(&manager, "stopped");
}

#[test]
fn stderr_read_failure_preserves_the_original_error_and_allows_retry_and_exit() {
    let path = std::env::temp_dir().join(format!("log-read-fault-{}", uuid::Uuid::new_v4()));
    let broken = Mutex::new(Some(File::create(&path).unwrap())); // Write-only handle.
    let manager = start(Arc::new(move |spec| {
        if let Some(stderr) = broken.lock().unwrap().take() {
            Ok(Box::new(WithStderr {
                child: stub(spec, "startup_error")?,
                stderr: Some(stderr),
            }))
        } else {
            stub(spec, "ready")
        }
    }));
    wait_logs(&manager, |logs| logs.read_error.is_some());
    let failed = wait_for(&manager, "failed");
    assert_eq!(failed.error.unwrap().code, "RuntimeDataInUseError");
    assert!(failed.can_retry);
    assert!(manager.retry().accepted);
    wait_for(&manager, "ready");
    assert!(manager.logs().read_error.is_none());
    manager.request_shutdown();
    wait_for(&manager, "stopped");
    std::fs::remove_file(path).unwrap();
}

#[test]
fn continuous_stderr_flood_stays_bounded_while_queries_and_shutdown_make_progress() {
    let manager = start(Arc::new(|spec| stub(spec, "continuous_logs")));
    wait_for(&manager, "ready");
    wait_logs(&manager, |logs| logs.truncated);
    for _ in 0..8 {
        let logs = manager.logs();
        assert_eq!(logs.retained_bytes, 1_048_576);
        assert!(logs.text.len() <= 1_048_576);
    }
    let started = Instant::now();
    manager.request_shutdown();
    wait_for(&manager, "stopped");
    assert!(started.elapsed() < Duration::from_secs(3));
}
