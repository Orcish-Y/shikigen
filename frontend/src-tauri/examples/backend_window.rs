//! Native window acceptance with an isolated project and a recoverable platform
//! observation fault. Not the shipped executable; no production fault flag.
use shikigen_desktop_lib::{
    backend::LaunchPlan,
    process::{self, ManagedProcess, SpawnSpec, Stdio},
};
use std::{io, path::PathBuf, sync::Arc, time::Duration};

struct QueryFault {
    child: Box<dyn ManagedProcess>,
    release: PathBuf,
}
impl ManagedProcess for QueryFault {
    fn take_stdio(&mut self) -> Option<Stdio> {
        self.child.take_stdio()
    }
    fn wait_exit(&self, timeout: Duration) -> io::Result<Option<u32>> {
        self.child.wait_exit(timeout)
    }
    fn terminate_tree(&self) -> io::Result<()> {
        self.child.terminate_tree()
    }
    fn wait_tree_empty(&self, timeout: Duration) -> io::Result<bool> {
        if !self.release.exists() {
            return Err(io::Error::other("injected recoverable Job query failure"));
        }
        self.child.wait_tree_empty(timeout)
    }
}
fn main() {
    let root = PathBuf::from(std::env::args_os().nth(1).expect("isolated project path"));
    let release = root.join("allow-observation");
    let mut context = tauri::generate_context!();
    // Acceptance windows must never notify or block a user's real application.
    context.config_mut().identifier = "dev.shikigen.desktop.acceptance".into();
    if root.join("missing-tray-icon").exists() {
        context.set_default_window_icon(None);
    }
    shikigen_desktop_lib::run_with_backend(
        Arc::new(move || {
            let starts = root.join("host-starts");
            std::fs::create_dir_all(&starts).unwrap();
            std::fs::write(starts.join(std::process::id().to_string()), "").unwrap();
            LaunchPlan::from_root(&root)
        }),
        Arc::new(move |spec: &SpawnSpec| {
            Ok(Box::new(QueryFault {
                child: process::spawn(spec)?,
                release: release.clone(),
            }))
        }),
        context,
    );
}
