pub mod backend;
pub mod process;
use backend::{BackendManager, BackendSnapshot, LaunchPlan};
use std::sync::Arc;
use tauri::{Emitter, Manager};

#[tauri::command]
fn get_backend_state(manager: tauri::State<'_, Arc<BackendManager>>) -> BackendSnapshot {
    manager.snapshot()
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let app = tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![get_backend_state])
        .setup(|app| {
            let handle = app.handle().clone();
            let manager = BackendManager::start(
                LaunchPlan::development(),
                Arc::new(process::spawn),
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
            match manager.snapshot().state.as_str() {
                "stopped" => {}
                "failed" => {
                    // Failed startup has no retry in this ticket. The manager's
                    // Job remains owned until confirmed cleanup or host exit.
                }
                _ => {
                    api.prevent_exit();
                    manager.request_shutdown();
                }
            }
        }
    });
}
