//! Platform ownership boundary. Every process creation in this host must use
//! this adapter (or an explicit handle whitelist), never broad inheritance.
use std::{ffi::OsString, fs::File, io, path::PathBuf, time::Duration};

pub struct SpawnSpec {
    pub executable: PathBuf,
    pub args: Vec<OsString>,
    pub cwd: PathBuf,
    /// Overrides inherited environment variables.
    pub env: Vec<(OsString, OsString)>,
}
pub struct Stdio {
    pub stdin: File,
    pub stdout: File,
    pub stderr: File,
}
pub trait ManagedProcess: Send {
    fn take_stdio(&mut self) -> Option<Stdio>;
    fn wait_exit(&self, timeout: Duration) -> io::Result<Option<u32>>;
    fn terminate_tree(&self) -> io::Result<()>;
    fn wait_tree_empty(&self, timeout: Duration) -> io::Result<bool>;
}
#[cfg(windows)]
mod windows;
#[cfg(windows)]
pub use windows::spawn;
#[cfg(not(windows))]
pub fn spawn(_: &SpawnSpec) -> io::Result<Box<dyn ManagedProcess>> {
    Err(io::Error::new(
        io::ErrorKind::Unsupported,
        "后端托管目前需要 Windows 10 或更新版本",
    ))
}
