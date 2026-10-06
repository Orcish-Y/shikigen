use crate::backend::{BackendManager, BackendSnapshot};
use serde::Serialize;
use std::sync::{Arc, Mutex};
use tauri::{
    menu::{Menu, MenuItem},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    Emitter, Manager,
};

pub(crate) struct Desktop {
    pub(crate) tray_error: Option<String>,
    notifications: Mutex<Notifications>,
    visibility: Mutex<WorkspaceVisibility>,
}

#[derive(Clone, Serialize)]
pub(crate) struct WorkspaceVisibility {
    revision: u64,
    visible: bool,
}

#[derive(Default)]
struct Notifications {
    revision: u64,
    fault_startup_id: Option<String>,
}

impl Desktop {
    pub(crate) fn install(app: &tauri::AppHandle) -> Self {
        let tray_error = create_tray(app)
            .err()
            .map(|error| format!("系统托盘不可用：{error}。关闭窗口将退出应用并停止后台任务。"));
        Self {
            tray_error,
            notifications: Mutex::default(),
            visibility: Mutex::new(WorkspaceVisibility {
                revision: 0,
                visible: true,
            }),
        }
    }
}

/// Read actual visibility after successful window operations. Focus and
/// minimization are independent; a failed read leaves the known value intact.
pub(crate) fn workspace_visibility(app: &tauri::AppHandle) -> Result<WorkspaceVisibility, String> {
    let window = app.get_webview_window("main").ok_or("主窗口不可用")?;
    let visible = window.is_visible().map_err(|error| error.to_string())?;
    let desktop = app.state::<Desktop>();
    let mut snapshot = desktop.visibility.lock().unwrap();
    if snapshot.visible != visible {
        snapshot.revision += 1;
        snapshot.visible = visible;
        if !visible {
            app.state::<Arc<crate::workspace_file_open::WorkspaceFileOpens>>()
                .invalidate_file_intents();
        }
        let _ = app.emit("workspace-visibility-changed", snapshot.clone());
    }
    Ok(snapshot.clone())
}

pub(crate) fn backend_changed(app: &tauri::AppHandle, snapshot: BackendSnapshot) {
    let handle = app.clone();
    let _ = app.run_on_main_thread(move || {
        let manager = handle.state::<Arc<BackendManager>>();
        // Commands and worker publications can arrive out of order. A queued
        // old attempt must never activate a window belonging to a new attempt.
        if snapshot.startup_id != manager.snapshot().startup_id {
            return;
        }
        let desktop = handle.state::<Desktop>();
        let mut notifications = desktop.notifications.lock().unwrap();
        if snapshot.revision <= notifications.revision {
            return;
        }
        notifications.revision = snapshot.revision;
        if snapshot.state == "stopped" {
            drop(notifications);
            handle.exit(0);
            return;
        }
        if snapshot.error.is_some() && notifications.fault_startup_id != snapshot.startup_id {
            // Record the first error even if already visible: closing after
            // seeing it must not be undone by later cleanup progress.
            notifications.fault_startup_id = snapshot.startup_id;
            drop(notifications);
            if let Some(window) = handle.get_webview_window("main") {
                if !window.is_visible().unwrap_or(true) || window.is_minimized().unwrap_or(false) {
                    show_main(&handle);
                }
            }
        }
    });
}

fn create_tray(app: &tauri::AppHandle) -> Result<(), String> {
    let icon = app.default_window_icon().cloned().ok_or("缺少应用图标")?;
    let open = MenuItem::with_id(app, "open-main", "打开主窗口", true, None::<&str>)
        .map_err(|e| e.to_string())?;
    let quit = MenuItem::with_id(app, "quit-app", "退出应用", true, None::<&str>)
        .map_err(|e| e.to_string())?;
    let menu = Menu::with_items(app, &[&open, &quit]).map_err(|e| e.to_string())?;
    let tray = TrayIconBuilder::with_id("main-tray")
        .icon(icon)
        .tooltip("Shikigen")
        .menu(&menu)
        .show_menu_on_left_click(false)
        .on_tray_icon_event(|tray, event| {
            if matches!(
                event,
                TrayIconEvent::Click {
                    button: MouseButton::Left,
                    button_state: MouseButtonState::Up,
                    ..
                }
            ) {
                activate(tray.app_handle());
            }
        })
        .on_menu_event(|app, event| match event.id.as_ref() {
            "open-main" => activate(app),
            "quit-app" => request_exit(app),
            _ => {}
        })
        .build(app)
        .map_err(|e| e.to_string())?;
    // tray-icon 0.24.2 can return Ok even when Shell_NotifyIconW(NIM_ADD)
    // failed. On Windows, rect() confirms registration with the shell.
    #[cfg(windows)]
    if !matches!(tray.rect(), Ok(Some(_))) {
        app.remove_tray_by_id(tray.id());
        return Err("Windows 未确认托盘图标注册成功".into());
    }
    Ok(())
}

pub(crate) fn close_requested(window: &tauri::Window, api: &tauri::CloseRequestApi) {
    if let Some(intents) = window.try_state::<Arc<crate::workspace_file_open::WorkspaceFileOpens>>()
    {
        intents.invalidate_file_intents();
    }
    let Some(manager) = window.try_state::<Arc<BackendManager>>() else {
        api.prevent_close();
        return;
    };
    if manager.snapshot().state == "stopped" {
        return;
    }
    api.prevent_close();
    if window.state::<Desktop>().tray_error.is_none() && !manager.is_shutting_down() {
        if window.hide().is_ok() {
            let _ = workspace_visibility(window.app_handle());
        }
    } else {
        request_exit(window.app_handle());
    }
}

pub(crate) fn request_exit(app: &tauri::AppHandle) {
    if let Some(intents) = app.try_state::<Arc<crate::workspace_file_open::WorkspaceFileOpens>>() {
        intents.invalidate_file_intents();
    }
    // Keep cleanup progress and any unconfirmed-reclamation error reachable.
    show_main(app);
    if let Some(manager) = app.try_state::<Arc<BackendManager>>() {
        manager.request_shutdown();
    }
}

fn show_main(app: &tauri::AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        if window.show().is_ok() {
            let _ = workspace_visibility(app);
        }
        let _ = window.unminimize();
        let _ = window.set_focus();
    }
}

pub(crate) fn activate(app: &tauri::AppHandle) {
    let app = app.clone();
    // Defer beyond the single-instance plugin's synchronous Windows IPC call.
    // run_on_main_thread alone executes inline when already on that thread.
    tauri::async_runtime::spawn(async move {
        let handle = app.clone();
        let _ = app.run_on_main_thread(move || {
            let Some(manager) = handle.try_state::<Arc<BackendManager>>() else {
                return;
            };
            if !manager.is_shutting_down() {
                show_main(&handle);
            }
        });
    });
}
