#![cfg(windows)]
use shikigen_desktop_lib::process::{spawn, SpawnSpec};
use std::{io::Read, path::PathBuf, time::Duration};

#[test]
fn process_receives_literal_arguments_and_can_be_reclaimed() {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    let mut child = spawn(&SpawnSpec {
        executable: root.join(".venv/Scripts/python.exe"),
        args: vec![
            "-c".into(),
            "import sys,time; print(repr(sys.argv[1:]),flush=True); time.sleep(60)".into(),
            "space and quote\"".into(),
            "tail\\".into(),
        ],
        cwd: root,
        env: vec![],
    })
    .unwrap();
    let mut streams = child.take_stdio().unwrap();
    let mut first = [0; 1];
    streams.stdout.read_exact(&mut first).unwrap();
    assert_eq!(first[0], b'[');
    assert_eq!(child.wait_exit(Duration::ZERO).unwrap(), None);
    assert!(!child.wait_tree_empty(Duration::ZERO).unwrap());
    child.terminate_tree().unwrap();
    assert!(child.wait_exit(Duration::from_secs(5)).unwrap().is_some());
    assert!(child.wait_tree_empty(Duration::from_secs(5)).unwrap());
    let mut output = String::new();
    streams.stdout.read_to_string(&mut output).unwrap();
    assert!(output.contains("space and quote\""));
    assert!(output.contains("tail\\\\"));
}

#[test]
fn failed_create_process_releases_job_and_pipe_handles() {
    use windows_sys::Win32::System::Threading::{GetCurrentProcess, GetProcessHandleCount};
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    // Stabilize lazy platform initialization before taking the baseline.
    let invalid = SpawnSpec {
        executable: root.join("missing-python.exe"),
        args: vec![],
        cwd: root,
        env: vec![],
    };
    assert!(spawn(&invalid).is_err());
    unsafe {
        let mut before = 0;
        assert_ne!(GetProcessHandleCount(GetCurrentProcess(), &mut before), 0);
        for _ in 0..30 {
            assert!(spawn(&invalid).is_err());
        }
        let mut after = 0;
        assert_ne!(GetProcessHandleCount(GetCurrentProcess(), &mut after), 0);
        // Other tests may close handles concurrently. Leaks would add 7+ per spawn.
        assert!(after <= before + 8, "handle count {before} -> {after}");
    }
}
