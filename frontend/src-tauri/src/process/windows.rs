use super::{ManagedProcess, SpawnSpec, Stdio};
use std::{
    collections::BTreeMap,
    ffi::OsStr,
    fs::File,
    io,
    mem::{size_of, zeroed},
    os::windows::{
        ffi::OsStrExt,
        io::{AsRawHandle, FromRawHandle, OwnedHandle},
    },
    ptr::{null, null_mut},
    sync::Mutex,
    thread,
    time::{Duration, Instant},
};
use windows_sys::Win32::{
    Foundation::*,
    Security::SECURITY_ATTRIBUTES,
    System::{JobObjects::*, Pipes::CreatePipe, Threading::*},
};

// Serializes the inheritable-endpoint window for all adapter spawns. Other host
// process creation must also use a whitelist; see the module-level contract.
static SPAWN_LOCK: Mutex<()> = Mutex::new(());
fn checked(ok: i32) -> io::Result<()> {
    if ok == 0 {
        Err(io::Error::last_os_error())
    } else {
        Ok(())
    }
}
fn wide(value: &OsStr) -> io::Result<Vec<u16>> {
    let mut units: Vec<u16> = value.encode_wide().collect();
    if units.contains(&0) {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "NUL in process argument",
        ));
    }
    units.push(0);
    Ok(units)
}
// CRT quoting, including quotes, trailing backslashes and empty arguments.
// CreateProcessW receives an explicit executable, never a shell command.
fn quote(value: &OsStr) -> io::Result<Vec<u16>> {
    let units = wide(value)?;
    let mut result = vec![34];
    let mut slashes = 0;
    for &unit in &units[..units.len() - 1] {
        if unit == 92 {
            slashes += 1;
            continue;
        }
        result.extend(std::iter::repeat_n(
            92,
            if unit == 34 { 2 * slashes + 1 } else { slashes },
        ));
        result.push(unit);
        slashes = 0;
    }
    result.extend(std::iter::repeat_n(92, 2 * slashes));
    result.push(34);
    Ok(result)
}
fn handle(h: &OwnedHandle) -> HANDLE {
    h.as_raw_handle()
}
fn pipe(parent_reads: bool) -> io::Result<(File, OwnedHandle)> {
    unsafe {
        let attrs = SECURITY_ATTRIBUTES {
            nLength: size_of::<SECURITY_ATTRIBUTES>() as u32,
            lpSecurityDescriptor: null_mut(),
            bInheritHandle: 1,
        };
        let (mut read, mut write) = (null_mut(), null_mut());
        checked(CreatePipe(&mut read, &mut write, &attrs, 0))?;
        let read = OwnedHandle::from_raw_handle(read);
        let write = OwnedHandle::from_raw_handle(write);
        let (parent, child) = if parent_reads {
            (read, write)
        } else {
            (write, read)
        };
        checked(SetHandleInformation(
            handle(&parent),
            HANDLE_FLAG_INHERIT,
            0,
        ))?;
        Ok((File::from(parent), child))
    }
}
struct Attributes {
    storage: Vec<usize>,
}
impl Attributes {
    fn new() -> io::Result<Self> {
        unsafe {
            let mut bytes = 0;
            InitializeProcThreadAttributeList(null_mut(), 2, 0, &mut bytes);
            if bytes == 0 {
                return Err(io::Error::last_os_error());
            }
            let mut storage = vec![0usize; bytes.div_ceil(size_of::<usize>())];
            checked(InitializeProcThreadAttributeList(
                storage.as_mut_ptr().cast(),
                2,
                0,
                &mut bytes,
            ))?;
            Ok(Self { storage })
        }
    }
    fn ptr(&mut self) -> LPPROC_THREAD_ATTRIBUTE_LIST {
        self.storage.as_mut_ptr().cast()
    }
}
impl Drop for Attributes {
    fn drop(&mut self) {
        unsafe {
            DeleteProcThreadAttributeList(self.ptr());
        }
    }
}
struct Process {
    job: OwnedHandle,
    process: OwnedHandle,
    stdio: Option<Stdio>,
}
impl ManagedProcess for Process {
    fn take_stdio(&mut self) -> Option<Stdio> {
        self.stdio.take()
    }
    fn wait_exit(&self, timeout: Duration) -> io::Result<Option<u32>> {
        unsafe {
            match WaitForSingleObject(
                handle(&self.process),
                timeout.as_millis().min((u32::MAX - 1) as u128) as u32,
            ) {
                WAIT_OBJECT_0 => {
                    let mut code = 0;
                    checked(GetExitCodeProcess(handle(&self.process), &mut code))?;
                    Ok(Some(code))
                }
                WAIT_TIMEOUT => Ok(None),
                _ => Err(io::Error::last_os_error()),
            }
        }
    }
    fn terminate_tree(&self) -> io::Result<()> {
        unsafe { checked(TerminateJobObject(handle(&self.job), 1)) }
    }
    fn wait_tree_empty(&self, timeout: Duration) -> io::Result<bool> {
        let started = Instant::now();
        loop {
            unsafe {
                let mut info: JOBOBJECT_BASIC_ACCOUNTING_INFORMATION = zeroed();
                checked(QueryInformationJobObject(
                    handle(&self.job),
                    JobObjectBasicAccountingInformation,
                    (&mut info as *mut JOBOBJECT_BASIC_ACCOUNTING_INFORMATION).cast(),
                    size_of::<JOBOBJECT_BASIC_ACCOUNTING_INFORMATION>() as u32,
                    null_mut(),
                ))?;
                if info.ActiveProcesses == 0 {
                    return Ok(true);
                }
            }
            if started.elapsed() >= timeout {
                return Ok(false);
            }
            thread::sleep(Duration::from_millis(10).min(timeout.saturating_sub(started.elapsed())));
        }
    }
}

pub fn spawn(spec: &SpawnSpec) -> io::Result<Box<dyn ManagedProcess>> {
    let executable = wide(spec.executable.as_os_str())?;
    let cwd = wide(spec.cwd.as_os_str())?;
    let mut command = quote(spec.executable.as_os_str())?;
    for argument in &spec.args {
        command.push(32);
        command.extend(quote(argument)?);
    }
    command.push(0);
    let mut environment: BTreeMap<Vec<u16>, (Vec<u16>, Vec<u16>)> = BTreeMap::new();
    for (name, value) in std::env::vars_os().chain(spec.env.iter().cloned()) {
        let name = wide(&name)?;
        let value = wide(&value)?;
        // Windows environment names are case-insensitive. Preserve original case.
        let key = String::from_utf16_lossy(&name)
            .to_uppercase()
            .encode_utf16()
            .collect();
        environment.insert(key, (name, value));
    }
    let mut block = Vec::new();
    for (name, value) in environment.values() {
        block.extend_from_slice(&name[..name.len() - 1]);
        block.push(61);
        block.extend(value);
    }
    block.push(0);
    let _guard = SPAWN_LOCK.lock().unwrap_or_else(|e| e.into_inner());
    unsafe {
        let raw_job = CreateJobObjectW(null(), null());
        if raw_job.is_null() {
            return Err(io::Error::last_os_error());
        }
        // NULL security attributes make the Job handle non-inheritable.
        let job = OwnedHandle::from_raw_handle(raw_job);
        let mut limits: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = zeroed();
        limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
        checked(SetInformationJobObject(
            handle(&job),
            JobObjectExtendedLimitInformation,
            (&limits as *const JOBOBJECT_EXTENDED_LIMIT_INFORMATION).cast(),
            size_of::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() as u32,
        ))?;
        let (stdin, child_in) = pipe(false)?;
        let (stdout, child_out) = pipe(true)?;
        let (stderr, child_err) = pipe(true)?;
        let mut jobs = [handle(&job)];
        let mut handles = [handle(&child_in), handle(&child_out), handle(&child_err)];
        let mut attrs = Attributes::new()?;
        checked(UpdateProcThreadAttribute(
            attrs.ptr(),
            0,
            PROC_THREAD_ATTRIBUTE_JOB_LIST as usize,
            jobs.as_mut_ptr().cast(),
            size_of_val(&jobs),
            null_mut(),
            null(),
        ))?;
        checked(UpdateProcThreadAttribute(
            attrs.ptr(),
            0,
            PROC_THREAD_ATTRIBUTE_HANDLE_LIST as usize,
            handles.as_mut_ptr().cast(),
            size_of_val(&handles),
            null_mut(),
            null(),
        ))?;
        let mut startup: STARTUPINFOEXW = zeroed();
        startup.StartupInfo.cb = size_of::<STARTUPINFOEXW>() as u32;
        startup.StartupInfo.dwFlags = STARTF_USESTDHANDLES;
        startup.StartupInfo.hStdInput = handles[0];
        startup.StartupInfo.hStdOutput = handles[1];
        startup.StartupInfo.hStdError = handles[2];
        startup.lpAttributeList = attrs.ptr();
        let mut info: PROCESS_INFORMATION = zeroed();
        checked(CreateProcessW(
            executable.as_ptr(),
            command.as_mut_ptr(),
            null(),
            null(),
            1,
            EXTENDED_STARTUPINFO_PRESENT | CREATE_UNICODE_ENVIRONMENT | CREATE_NO_WINDOW,
            block.as_ptr().cast(),
            cwd.as_ptr(),
            &startup.StartupInfo,
            &mut info,
        ))?;
        // No fallible operations after creation. RAII closes thread + child pipe
        // duplicates before returning; any earlier failure closes the entire Job.
        let process = OwnedHandle::from_raw_handle(info.hProcess);
        let _thread = OwnedHandle::from_raw_handle(info.hThread);
        Ok(Box::new(Process {
            job,
            process,
            stdio: Some(Stdio {
                stdin,
                stdout,
                stderr,
            }),
        }))
    }
}
