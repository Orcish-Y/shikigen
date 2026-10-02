pub mod backend;
mod desktop;
pub mod process;
mod single_instance;
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

#[tauri::command]
fn get_tray_error(desktop: tauri::State<'_, desktop::Desktop>) -> Option<String> {
    desktop.tray_error.clone()
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    run_with_backend(
        Arc::new(LaunchPlan::development),
        Arc::new(process::spawn),
        tauri::generate_context!(),
    );
}

/// The native acceptance host supplies an isolated project and platform faults.
/// The shipped entry always uses the development plan and Windows adapter.
pub fn run_with_backend(
    load_plan: backend::PlanLoader,
    launcher: backend::Launcher,
    context: tauri::Context<tauri::Wry>,
) {
    // The plugin's Windows mutex is published before its notification window.
    // Serialize this short initialization interval, before any runtime/windows.
    #[cfg(windows)]
    let startup_guard = single_instance::StartupGuard::acquire(&context.config().identifier)
        .expect("无法取得桌面单实例启动锁");
    let builder = tauri::Builder::default();
    #[cfg(desktop)]
    let builder = builder.plugin(tauri_plugin_single_instance::init(|app, _, _| {
        desktop::activate(app);
    }));
    let app = builder
        .invoke_handler(tauri::generate_handler![
            get_backend_state,
            retry_backend,
            get_tray_error
        ])
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                desktop::close_requested(window, api);
            }
        })
        .setup(move |app| {
            let handle = app.handle().clone();
            app.manage(desktop::Desktop::install(&handle));
            let manager = BackendManager::start(
                load_plan,
                launcher,
                Arc::new(move |snapshot| {
                    let _ = handle.emit("backend-state-changed", &snapshot);
                    desktop::backend_changed(&handle, snapshot);
                }),
            );
            app.manage(manager);
            Ok(())
        })
        .build(context)
        .expect("failed to build Shikigen desktop application");
    #[cfg(windows)]
    {
        // build initializes plugins; run below creates the visible window and
        // executes setup. Reject the plugin's missing-owner race before both.
        if !single_instance::owns_notification_window(&app.config().identifier) {
            eprintln!("未取得桌面单实例通知窗口，取消本次启动");
            app.cleanup_before_exit();
            std::process::exit(0);
        }
        drop(startup_guard);
    }
    app.run(|handle, event| {
        if let tauri::RunEvent::ExitRequested { api, .. } = event {
            let manager = handle.state::<Arc<BackendManager>>();
            if manager.snapshot().state != "stopped" {
                api.prevent_exit();
                desktop::request_exit(handle);
            }
        }
    });
}
