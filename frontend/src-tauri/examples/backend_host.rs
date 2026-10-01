//! Console host for native acceptance: same manager and Job adapter as Tauri.
//! An optional absolute project root lets tests use isolated data and environment.
use shikigen_desktop_lib::{
    backend::{BackendManager, LaunchPlan},
    process,
};
use std::{
    io::{self, BufRead, Write},
    path::PathBuf,
    sync::Arc,
    thread,
    time::Duration,
};
fn main() {
    let plan = match std::env::args_os().nth(1) {
        Some(root) => LaunchPlan::from_root(&PathBuf::from(root)),
        None => LaunchPlan::development(),
    };
    let manager = BackendManager::start(
        plan,
        Arc::new(process::spawn),
        Arc::new(|state| {
            println!("{}", serde_json::to_string(&state).unwrap());
            let _ = io::stdout().flush();
        }),
    );
    for line in io::stdin().lock().lines() {
        if matches!(line.as_deref(), Ok("shutdown")) {
            break;
        }
    }
    manager.request_shutdown();
    loop {
        if manager.snapshot().state == "stopped" {
            break;
        }
        thread::sleep(Duration::from_millis(10));
    }
}
