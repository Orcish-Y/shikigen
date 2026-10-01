pub mod backend;
pub mod process;
use backend::{BackendManager, BackendSnapshot, LaunchPlan};
use std::sync::Arc;
use tauri::{Emitter, Manager};

#[tauri::command]
fn get_backend_state(manager: tauri::State<'_, Arc<BackendManager>>) -> BackendSnapshot {
    manager.snapshot()
}

#[tauri::command]
fn retry_backend(manager: tauri::State<'_, Arc<BackendManager>>) -> backend::RetryResult {
    manager.inner().retry()
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    run_with_backend(Arc::new(LaunchPlan::development), Arc::new(process::spawn));
}

/// The native acceptance host supplies an isolated project and platform faults.
/// The shipped entry always uses the development plan and Windows adapter.
pub fn run_with_backend(load_plan: backend::PlanLoader, launcher: backend::Launcher) {
    let app = tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![get_backend_state, retry_backend])
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                let manager = window.state::<Arc<BackendManager>>();
                if manager.snapshot().state != "stopped" {
                    // Keep the last window alive while cleanup is unconfirmed.
                    api.prevent_close();
                    manager.request_shutdown();
                }
            }
        })
        .setup(move |app| {
            let handle = app.handle().clone();
            let manager = BackendManager::start(
                load_plan,
                launcher,
                Arc::new(move |snapshot| {
                    let _ = handle.emit("backend-state-changed", &snapshot);
                    if snapshot.state == "stopped" {
                        handle.exit(0);
                    }
                }),
            );
            app.manage(manager);
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("failed to build Shikigen desktop application");
    app.run(|handle, event| {
        if let tauri::RunEvent::ExitRequested { api, .. } = event {
            let manager = handle.state::<Arc<BackendManager>>();
            if manager.snapshot().state != "stopped" {
                api.prevent_exit();
                manager.request_shutdown();
            }
        }
    });
}
