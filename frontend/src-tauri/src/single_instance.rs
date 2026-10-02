#[cfg(windows)]
pub(crate) use windows::{owns_notification_window, StartupGuard};

#[cfg(windows)]
mod windows {
    use std::{
        io,
        marker::PhantomData,
        os::windows::io::{AsRawHandle, FromRawHandle, OwnedHandle},
        rc::Rc,
    };
    use windows_sys::Win32::{
        Foundation::{WAIT_ABANDONED, WAIT_OBJECT_0, WAIT_TIMEOUT},
        System::Threading::{CreateMutexW, GetCurrentProcessId, ReleaseMutex, WaitForSingleObject},
        UI::WindowsAndMessaging::{FindWindowW, GetWindowThreadProcessId},
    };

    // A thread owns the mutex, so its guard must not move to another thread.
    pub(crate) struct StartupGuard(OwnedHandle, PhantomData<Rc<()>>);

    pub(crate) fn owns_notification_window(identifier: &str) -> bool {
        // These names belong to the pinned single-instance plugin's Windows
        // protocol. Recheck on upgrades. If the old owner exits between the
        // plugin's mutex check and FindWindowW, the plugin can return without
        // creating its own endpoint. Such a host must never start a backend.
        let class: Vec<u16> = format!("{identifier}-sic\0").encode_utf16().collect();
        let name: Vec<u16> = format!("{identifier}-siw\0").encode_utf16().collect();
        unsafe {
            let window = FindWindowW(class.as_ptr(), name.as_ptr());
            if window.is_null() {
                return false;
            }
            let mut owner = 0;
            GetWindowThreadProcessId(window, &mut owner);
            owner == GetCurrentProcessId()
        }
    }

    impl StartupGuard {
        pub(crate) fn acquire(identifier: &str) -> io::Result<Self> {
            let name: Vec<u16> = format!("{identifier}-startup-gate\0")
                .encode_utf16()
                .collect();
            unsafe {
                // Default security attributes keep this handle non-inheritable.
                let raw = CreateMutexW(std::ptr::null(), 0, name.as_ptr());
                if raw.is_null() {
                    return Err(io::Error::last_os_error());
                }
                let handle = OwnedHandle::from_raw_handle(raw);
                match WaitForSingleObject(raw, 30_000) {
                    // A secondary exits inside the plugin, without Rust drops.
                    // Windows abandons its gate; the next caller safely owns it.
                    WAIT_OBJECT_0 | WAIT_ABANDONED => Ok(Self(handle, PhantomData)),
                    WAIT_TIMEOUT => Err(io::Error::new(
                        io::ErrorKind::TimedOut,
                        "等待已有桌面实例完成单实例检查超时",
                    )),
                    _ => Err(io::Error::last_os_error()),
                }
            }
        }
    }

    impl Drop for StartupGuard {
        fn drop(&mut self) {
            unsafe {
                ReleaseMutex(self.0.as_raw_handle());
            }
        }
    }
}
