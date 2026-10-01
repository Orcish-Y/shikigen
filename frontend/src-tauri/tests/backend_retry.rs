#![cfg(windows)]
use shikigen_desktop_lib::{
    backend::{BackendManager, BackendSnapshot, LaunchPlan, PlanLoader},
    process::{self, SpawnSpec},
};
use std::{
    fs,
    path::PathBuf,
    sync::{
        atomic::{AtomicUsize, Ordering},
        Arc, Barrier, Condvar, Mutex,
    },
    thread,
    time::{Duration, Instant},
};

struct Project(PathBuf);
impl Project {
    fn new() -> Self {
        let project = Self(std::env::temp_dir().join(format!("retry-{}", uuid::Uuid::new_v4())));
        fs::create_dir_all(project.0.join("app")).unwrap();
        fs::create_dir_all(project.0.join(".venv/Scripts")).unwrap();
        fs::write(project.0.join("pyproject.toml"), "").unwrap();
        fs::write(project.0.join("app/desktop.py"), "").unwrap();
        let dev = LaunchPlan::development().unwrap();
        fs::copy(dev.python, project.0.join(".venv/Scripts/python.exe")).unwrap();
        fs::copy(
            dev.root.join(".venv/pyvenv.cfg"),
            project.0.join(".venv/pyvenv.cfg"),
        )
        .unwrap();
        project
    }
    fn config(&self, text: &str) {
        fs::write(self.0.join("config.json"), text).unwrap();
    }
    fn loader(&self) -> PlanLoader {
        let root = self.0.clone();
        Arc::new(move || LaunchPlan::from_root(&root))
    }
}
impl Drop for Project {
    fn drop(&mut self) {
        fs::remove_dir_all(&self.0).unwrap();
    }
}
fn wait_for(manager: &BackendManager, target: &str) -> BackendSnapshot {
    let deadline = Instant::now() + Duration::from_secs(10);
    loop {
        let state = manager.snapshot();
        if state.state == target {
            return state;
        }
        assert!(Instant::now() < deadline, "{state:?}");
        thread::sleep(Duration::from_millis(5));
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
fn fixing_configuration_and_retrying_recovers_without_restarting_the_host() {
    let project = Project::new();
    project.config(r#"{"backend":{"port":null}}"#);
    let count = Arc::new(AtomicUsize::new(0));
    let spawned = count.clone();
    let manager = BackendManager::start(
        project.loader(),
        Arc::new(move |spec| {
            spawned.fetch_add(1, Ordering::SeqCst);
            stub(spec, "ready")
        }),
        Arc::new(|_| {}),
    );
    let failed = wait_for(&manager, "failed");
    assert!(failed.can_retry);
    assert_eq!(failed.error.unwrap().code, "config");
    assert_eq!(count.load(Ordering::SeqCst), 0);
    project.config(
        r#"{"backend":{"port":45230,"startup_timeout_seconds":5,"shutdown_timeout_seconds":0.1}}"#,
    );
    let response = manager.retry();
    assert!(response.accepted);
    assert!(response.reason.is_none());
    assert_eq!(response.snapshot.state, "starting");
    assert!(!response.snapshot.can_retry);
    assert!(response.snapshot.error.is_none());
    assert!(response.snapshot.base_url.is_none());
    assert_ne!(response.snapshot.startup_id, failed.startup_id);
    assert!(response.snapshot.revision > failed.revision);
    let rejected = manager.retry();
    assert!(!rejected.accepted);
    assert!(rejected.reason.is_some());
    let ready = wait_for(&manager, "ready");
    assert_eq!(ready.startup_id, response.snapshot.startup_id);
    assert!(ready.revision > response.snapshot.revision);
    assert_eq!(count.load(Ordering::SeqCst), 1);
    manager.request_shutdown();
    wait_for(&manager, "stopped");
    assert!(!manager.retry().accepted);
}

#[test]
fn concurrent_retries_accept_once_and_quit_cancels_the_pending_launch() {
    let project = Project::new();
    project.config(r#"{"backend":null}"#);
    let load = project.loader();
    let loading = Arc::new(Barrier::new(2));
    let release = Arc::new((Mutex::new(false), Condvar::new()));
    let worker_loading = loading.clone();
    let worker_release = release.clone();
    let attempts = AtomicUsize::new(0);
    let count = Arc::new(AtomicUsize::new(0));
    let spawned = count.clone();
    let manager = BackendManager::start(
        Arc::new(move || {
            if attempts.fetch_add(1, Ordering::SeqCst) > 0 {
                worker_loading.wait();
                let (lock, changed) = &*worker_release;
                drop(
                    changed
                        .wait_while(lock.lock().unwrap(), |released| !*released)
                        .unwrap(),
                );
            }
            load()
        }),
        Arc::new(move |spec| {
            spawned.fetch_add(1, Ordering::SeqCst);
            stub(spec, "ready")
        }),
        Arc::new(|_| {}),
    );
    let failed = wait_for(&manager, "failed");
    project.config("{}");
    let start = Arc::new(Barrier::new(17));
    let mut clicks = Vec::new();
    for _ in 0..16 {
        let manager = manager.clone();
        let start = start.clone();
        clicks.push(thread::spawn(move || {
            start.wait();
            manager.retry()
        }));
    }
    start.wait();
    let replies: Vec<_> = clicks.into_iter().map(|t| t.join().unwrap()).collect();
    assert_eq!(replies.iter().filter(|r| r.accepted).count(), 1);
    assert!(replies.iter().all(|r| r.snapshot.state == "starting"));
    assert!(replies
        .iter()
        .all(|r| r.snapshot.revision == failed.revision + 1));
    loading.wait(); // Commands already returned while loading remains blocked.
    manager.request_shutdown();
    assert_eq!(manager.snapshot().state, "stopping");
    let refused = manager.retry();
    assert!(!refused.accepted);
    assert!(refused.reason.unwrap().contains("退出"));
    *release.0.lock().unwrap() = true;
    release.1.notify_one();
    wait_for(&manager, "stopped");
    assert_eq!(count.load(Ordering::SeqCst), 0);
    assert!(!manager.retry().accepted);
}

#[test]
fn each_attempt_keeps_its_config_budget_and_ignores_the_previous_protocol_id() {
    let project = Project::new();
    project.config(r#"{"backend":{"port":45231,"startup_timeout_seconds":0.8,"shutdown_timeout_seconds":0.3}}"#);
    let spawned = Arc::new(Barrier::new(2));
    let launched = spawned.clone();
    let ids = Arc::new(Mutex::new(Vec::<String>::new()));
    let launched_ids = ids.clone();
    let started = Instant::now();
    let manager = BackendManager::start(
        project.loader(),
        Arc::new(move |spec| {
            let mut ids = launched_ids.lock().unwrap();
            let id = spec.args[5].to_string_lossy().to_string();
            let port = spec.args[7].to_string_lossy().to_string();
            if ids.is_empty() {
                assert_eq!(port, "45231");
                ids.push(id);
                let child = stub(spec, "timeout")?;
                launched.wait();
                Ok(child)
            } else {
                assert_eq!(port, "45232");
                let mut args = spec.args.clone();
                args.splice(
                    0..2,
                    [PathBuf::from(env!("CARGO_MANIFEST_DIR"))
                        .join("tests/fixtures/backend_stub.py")
                        .into_os_string()],
                );
                let child = process::spawn(&SpawnSpec {
                    executable: spec.executable.clone(),
                    cwd: spec.cwd.clone(),
                    args,
                    env: vec![
                        ("BACKEND_TEST_MODE".into(), "old_message".into()),
                        ("BACKEND_TEST_OLD_ID".into(), ids[0].clone().into()),
                    ],
                })?;
                ids.push(id);
                Ok(child)
            }
        }),
        Arc::new(|_| {}),
    );
    spawned.wait();
    let changed = Instant::now();
    project.config(
        r#"{"backend":{"port":45232,"startup_timeout_seconds":5,"shutdown_timeout_seconds":5}}"#,
    );
    let failed = wait_for(&manager, "failed");
    assert_eq!(failed.error.unwrap().code, "startup_timeout");
    assert!(failed.can_retry);
    assert!(started.elapsed() >= Duration::from_secs(1));
    assert!(changed.elapsed() < Duration::from_secs(3));
    assert_eq!(ids.lock().unwrap().len(), 1); // No automatic restart.
    let retry = manager.retry();
    assert!(retry.accepted);
    let ready = wait_for(&manager, "ready");
    assert_eq!(ready.startup_id, retry.snapshot.startup_id);
    assert_ne!(ready.startup_id, failed.startup_id);
    assert_eq!(ids.lock().unwrap().len(), 2);
    manager.request_shutdown();
    wait_for(&manager, "stopped");
}
