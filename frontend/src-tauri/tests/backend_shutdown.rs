#![cfg(windows)]
use shikigen_desktop_lib::{
    backend::{BackendManager, BackendSnapshot, LaunchPlan},
    process::{self, ManagedProcess, SpawnSpec, Stdio},
};
use std::{
    io,
    sync::{
        atomic::{AtomicBool, AtomicU8, Ordering},
        Arc, Mutex,
    },
    thread,
    time::{Duration, Instant},
};

const OBSERVATION_OK: u8 = 0;
const JOB_QUERY_FAILED: u8 = 1;
const MAIN_EXIT_PENDING: u8 = 2;

// Fault injection at the platform observation boundary; the process, pipes and
// Job are real. A query error cannot reliably be induced in a healthy kernel.
struct ObservedProcess {
    inner: Box<dyn ManagedProcess>,
    forced: bool,
    gate: Arc<AtomicU8>,
    terminated: Arc<AtomicBool>,
}
impl ManagedProcess for ObservedProcess {
    fn take_stdio(&mut self) -> Option<Stdio> {
        self.inner.take_stdio()
    }
    fn wait_exit(&self, timeout: Duration) -> io::Result<Option<u32>> {
        if self.terminated.load(Ordering::SeqCst)
            && self.gate.load(Ordering::SeqCst) == MAIN_EXIT_PENDING
        {
            return Ok(None); // A zero Job count alone must not confirm exit.
        }
        self.inner.wait_exit(timeout)
    }
    fn terminate_tree(&self) -> io::Result<()> {
        self.terminated.store(true, Ordering::SeqCst);
        self.inner.terminate_tree()
    }
    fn wait_tree_empty(&self, timeout: Duration) -> io::Result<bool> {
        if self.terminated.load(Ordering::SeqCst)
            && self.gate.load(Ordering::SeqCst) == JOB_QUERY_FAILED
        {
            return Err(io::Error::other("injected Job query failure"));
        }
        if self.forced && !self.terminated.load(Ordering::SeqCst) {
            return Ok(false);
        }
        self.inner.wait_tree_empty(timeout)
    }
}

fn wait_for(
    manager: &BackendManager,
    predicate: impl Fn(&BackendSnapshot) -> bool,
) -> BackendSnapshot {
    let started = Instant::now();
    loop {
        let snapshot = manager.snapshot();
        if predicate(&snapshot) {
            return snapshot;
        }
        assert!(started.elapsed() < Duration::from_secs(10), "{snapshot:?}");
        thread::sleep(Duration::from_millis(5));
    }
}

fn managed_fault(
    gate: Arc<AtomicU8>,
    explicit: bool,
) -> (Arc<BackendManager>, Arc<Mutex<Vec<BackendSnapshot>>>) {
    let mut plan = LaunchPlan::development().unwrap();
    plan.config.startup_timeout_seconds = if explicit { 10.0 } else { 0.2 };
    plan.config.shutdown_timeout_seconds = 0.1;
    let events = Arc::new(Mutex::new(Vec::new()));
    let published = events.clone();
    let spawned = Arc::new(AtomicBool::new(false));
    let launched = spawned.clone();
    let manager = BackendManager::start(
        Ok(plan),
        Arc::new(move |spec| {
            let child = process::spawn(&SpawnSpec {
                executable: spec.executable.clone(),
                cwd: spec.cwd.clone(),
                args: vec!["-c".into(), "import time; time.sleep(60)".into()],
                env: vec![],
            })?;
            launched.store(true, Ordering::SeqCst);
            Ok(Box::new(ObservedProcess {
                inner: child,
                forced: true,
                gate: gate.clone(),
                terminated: Arc::new(AtomicBool::new(false)),
            }))
        }),
        Arc::new(move |s| published.lock().unwrap().push(s)),
    );
    let deadline = Instant::now() + Duration::from_secs(5);
    while !spawned.load(Ordering::SeqCst) {
        assert!(Instant::now() < deadline);
        thread::sleep(Duration::from_millis(5));
    }
    if explicit {
        manager.request_shutdown();
    }
    (manager, events)
}

#[test]
fn failed_observation_keeps_quit_pending_until_both_resources_are_confirmed() {
    let gate = Arc::new(AtomicU8::new(JOB_QUERY_FAILED));
    let (manager, events) = managed_fault(gate.clone(), true);
    let unconfirmed = wait_for(&manager, |s| s.state == "failed");
    assert_eq!(unconfirmed.error.unwrap().code, "reclamation_unconfirmed");
    assert!(!unconfirmed.can_retry);
    assert!(unconfirmed.base_url.is_none());
    manager.request_shutdown();
    thread::sleep(Duration::from_millis(300));
    assert_eq!(manager.snapshot().state, "failed");
    gate.store(OBSERVATION_OK, Ordering::SeqCst);
    wait_for(&manager, |s| s.state == "stopped");
    let events = events.lock().unwrap();
    assert!(events.iter().any(|s| s.state == "stopping"));
    assert!(events.iter().any(|s| s.state == "reclaiming"));
    assert!(events.iter().all(|s| s.base_url.is_none() && !s.can_retry));
}

#[test]
fn late_confirmation_restores_original_fault_without_automatically_stopping() {
    let gate = Arc::new(AtomicU8::new(JOB_QUERY_FAILED));
    let (manager, _) = managed_fault(gate.clone(), false);
    let failed = wait_for(&manager, |s| s.state == "failed");
    assert_eq!(failed.error.unwrap().code, "reclamation_unconfirmed");
    gate.store(OBSERVATION_OK, Ordering::SeqCst);
    let recovered = wait_for(&manager, |s| {
        s.error
            .as_ref()
            .is_some_and(|e| e.code == "startup_timeout")
            && s.state == "failed"
    });
    assert!(recovered.revision > failed.revision);
    manager.request_shutdown();
    assert_eq!(manager.snapshot().state, "stopped");
}

#[test]
fn zero_job_count_without_main_exit_exhausts_only_one_five_second_confirmation() {
    let gate = Arc::new(AtomicU8::new(MAIN_EXIT_PENDING));
    let started = Instant::now();
    let (manager, _) = managed_fault(gate.clone(), true);
    let failed = wait_for(&manager, |s| s.state == "failed");
    assert_eq!(failed.error.unwrap().code, "reclamation_unconfirmed");
    assert!(started.elapsed() >= Duration::from_secs(5));
    assert!(started.elapsed() < Duration::from_secs(7));
    gate.store(OBSERVATION_OK, Ordering::SeqCst);
    wait_for(&manager, |s| s.state == "stopped");
}

#[test]
fn quit_wins_late_health_and_the_cleanup_budget_includes_probe_time() {
    let marker = std::env::temp_dir().join(format!("probe-{}", uuid::Uuid::new_v4()));
    let probe_marker = marker.clone();
    let mut plan = LaunchPlan::development().unwrap();
    plan.config.startup_timeout_seconds = 5.0;
    plan.config.shutdown_timeout_seconds = 0.9;
    let events = Arc::new(Mutex::new(Vec::<BackendSnapshot>::new()));
    let published = events.clone();
    let manager = BackendManager::start(
        Ok(plan),
        Arc::new(move |spec| {
            let mut args = spec.args.clone();
            args.splice(
                0..2,
                [std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"))
                    .join("tests/fixtures/backend_stub.py")
                    .into_os_string()],
            );
            process::spawn(&SpawnSpec {
                executable: spec.executable.clone(),
                cwd: spec.cwd.clone(),
                args,
                env: vec![
                    ("BACKEND_TEST_MODE".into(), "late_ready".into()),
                    (
                        "BACKEND_TEST_PROBE_STARTED".into(),
                        probe_marker.clone().into_os_string(),
                    ),
                ],
            })
        }),
        Arc::new(move |s| published.lock().unwrap().push(s)),
    );
    let deadline = Instant::now() + Duration::from_secs(5);
    while !marker.exists() {
        assert!(Instant::now() < deadline);
        thread::sleep(Duration::from_millis(5));
    }
    let requested = Instant::now();
    manager.request_shutdown();
    thread::sleep(Duration::from_millis(100));
    manager.request_shutdown(); // Does not reset the total deadline.
    wait_for(&manager, |s| s.state == "stopped");
    assert!(requested.elapsed() < Duration::from_millis(1400));
    let events = events.lock().unwrap();
    assert!(events
        .iter()
        .all(|s| s.state != "ready" && s.base_url.is_none()));
    assert!(events.iter().any(|s| s.state == "reclaiming"));
    std::fs::remove_file(marker).unwrap();
}
