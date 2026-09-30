#![cfg(windows)]
use shikigen_desktop_lib::backend::{BackendManager, LaunchPlan};
use std::{
    sync::Arc,
    thread,
    time::{Duration, Instant},
};

#[test]
fn invalid_environment_is_a_visible_failure_without_an_address() {
    let manager = BackendManager::start(
        LaunchPlan::from_root(std::path::Path::new("Z:/missing shikigen project")),
        Arc::new(shikigen_desktop_lib::process::spawn),
        Arc::new(|_| {}),
    );
    let deadline = Instant::now() + Duration::from_secs(3);
    while manager.snapshot().state == "starting" {
        assert!(Instant::now() < deadline);
        thread::sleep(Duration::from_millis(10));
    }
    let state = manager.snapshot();
    assert_eq!(state.state, "failed");
    assert!(state.base_url.is_none());
    assert!(!state.can_retry);
    assert_eq!(state.error.unwrap().code, "project_path");
}

fn fixture_manager(mode: &str, timeout: f64) -> Arc<BackendManager> {
    let mut plan = LaunchPlan::development().unwrap();
    plan.config.startup_timeout_seconds = timeout;
    plan.config.shutdown_timeout_seconds = 0.1;
    let mode = mode.to_string();
    BackendManager::start(
        Ok(plan),
        Arc::new(move |spec| {
            let mut args = spec.args.clone();
            args.splice(
                0..2,
                [std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"))
                    .join("tests/fixtures/backend_stub.py")
                    .into_os_string()],
            );
            shikigen_desktop_lib::process::spawn(&shikigen_desktop_lib::process::SpawnSpec {
                executable: spec.executable.clone(),
                cwd: spec.cwd.clone(),
                args,
                env: vec![("BACKEND_TEST_MODE".into(), mode.clone().into())],
            })
        }),
        Arc::new(|_| {}),
    )
}
fn wait_state(
    manager: &BackendManager,
    target: &str,
) -> shikigen_desktop_lib::backend::BackendSnapshot {
    let started = Instant::now();
    loop {
        let state = manager.snapshot();
        if state.state == target {
            return state;
        }
        assert!(
            started.elapsed() < Duration::from_secs(10),
            "waiting for {target}, got {state:?}"
        );
        thread::sleep(Duration::from_millis(10));
    }
}
#[test]
fn bound_is_probed_before_publishing_ready_and_shutdown_revokes_address() {
    let manager = fixture_manager("ready", 5.0);
    let ready = wait_state(&manager, "ready");
    assert!(ready.base_url.unwrap().starts_with("http://127.0.0.1:"));
    assert!(!ready.can_retry);
    manager.request_shutdown();
    let stopped = wait_state(&manager, "stopped");
    assert!(stopped.base_url.is_none());
    assert!(stopped.revision > ready.revision);
}

#[test]
fn health_protocol_and_timeout_failures_never_publish_an_address() {
    for (mode, code) in [
        ("wrong_identity", "health_identity"),
        ("wrong_version", "health_identity"),
        ("oversize", "protocol"),
        ("startup_error", "RuntimeDataInUseError"),
        ("timeout", "startup_timeout"),
        ("unready", "startup_timeout"),
        ("slow_health", "startup_timeout"),
    ] {
        let manager = fixture_manager(mode, 0.6);
        let state = wait_state(&manager, "failed");
        assert!(state.base_url.is_none(), "{mode}");
        assert!(!state.can_retry);
        assert_eq!(state.error.unwrap().code, code, "{mode}");
    }
}
#[test]
fn old_messages_and_log_flood_do_not_block_startup_or_shutdown() {
    for mode in ["old_message", "stderr_flood"] {
        let manager = fixture_manager(mode, 5.0);
        wait_state(&manager, "ready");
        manager.request_shutdown();
        wait_state(&manager, "stopped");
    }
}
#[test]
fn unexpected_exit_revokes_ready_address() {
    let manager = fixture_manager("exit_after_ready", 5.0);
    wait_state(&manager, "ready");
    let failed = wait_state(&manager, "failed");
    assert!(failed.base_url.is_none());
    assert!(!failed.can_retry);
}

#[test]
fn timeout_reading_health_body_obeys_the_startup_deadline() {
    let started = Instant::now();
    let manager = fixture_manager("slow_body", 0.6);
    let failed = wait_state(&manager, "failed");
    assert_eq!(failed.error.unwrap().code, "startup_timeout");
    assert!(started.elapsed() < Duration::from_secs(3));
}

#[test]
fn old_output_flood_cannot_hide_main_process_exit() {
    let manager = fixture_manager("old_flood_exit", 5.0);
    wait_state(&manager, "ready");
    let failed = wait_state(&manager, "failed");
    assert!(failed.base_url.is_none());
    assert_eq!(failed.error.unwrap().code, "backend_exit");
}
