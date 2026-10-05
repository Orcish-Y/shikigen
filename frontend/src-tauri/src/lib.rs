pub mod backend;
mod desktop;
pub mod process;
mod single_instance;
pub mod web_open;
use backend::{BackendManager, BackendSnapshot, LaunchPlan};
use std::sync::Arc;
use tauri::{Emitter, Manager};
use tauri_plugin_opener::OpenerExt;

#[tauri::command]
async fn open_web_url(
    app: tauri::AppHandle,
    window: tauri::WebviewWindow,
    url: String,
) -> Result<bool, web_open::WebOpenError> {
    if window.label() != "main" {
        return Err(web_open::WebOpenError {
            code: "invalid_window",
            message: "网页打开仅限主窗口".into(),
        });
    }
    tauri::async_runtime::spawn_blocking(move || {
        web_open::open_web_url(&url, |validated| {
            app.opener()
                .open_url(validated, None::<&str>)
                .map_err(|error| error.to_string())
        })
    })
    .await
    .map_err(|error| web_open::WebOpenError {
        code: "web_open_failed",
        message: error.to_string(),
    })?
}

#[tauri::command]
fn get_backend_state(manager: tauri::State<'_, Arc<BackendManager>>) -> BackendSnapshot {
    manager.snapshot()
}

#[tauri::command]
async fn get_backend_logs(
    manager: tauri::State<'_, Arc<BackendManager>>,
) -> Result<backend::BackendLogs, String> {
    let manager = manager.inner().clone();
    tauri::async_runtime::spawn_blocking(move || manager.logs())
        .await
        .map_err(|_| "无法读取本次启动日志".into())
}

#[tauri::command]
fn retry_backend(manager: tauri::State<'_, Arc<BackendManager>>) -> backend::RetryResult {
    manager.inner().retry()
}

#[tauri::command]
fn get_tray_error(desktop: tauri::State<'_, desktop::Desktop>) -> Option<String> {
    desktop.tray_error.clone()
}

#[tauri::command]
async fn get_workspace_visibility(
    app: tauri::AppHandle,
) -> Result<desktop::WorkspaceVisibility, String> {
    // Read and publish on the same native event loop as hide/show. An older
    // cross-thread visibility read must not acquire a newer revision.
    let (send, mut receive) = tauri::async_runtime::channel(1);
    let handle = app.clone();
    app.run_on_main_thread(move || {
        let _ = send.try_send(desktop::workspace_visibility(&handle));
    })
    .map_err(|error| error.to_string())?;
    receive.recv().await.ok_or("主窗口状态查询已结束")?
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
        .plugin(
            tauri_plugin_opener::Builder::new()
                .open_js_links_on_click(false)
                .build(),
        )
        .invoke_handler(tauri::generate_handler![
            get_backend_state,
            get_backend_logs,
            retry_backend,
            get_tray_error,
            get_workspace_visibility,
            open_web_url
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
