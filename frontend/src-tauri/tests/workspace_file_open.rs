use shikigen_desktop_lib::{backend::BackendSnapshot, workspace_file_open::WorkspaceFileOpens};
use std::{
    fs,
    io::{BufRead, BufReader, Write},
    net::{TcpListener, TcpStream},
    sync::{
        atomic::{AtomicBool, AtomicUsize, Ordering},
        mpsc, Arc, Mutex,
    },
    thread,
    time::{Duration, Instant},
};

struct ResourceServer {
    root: std::path::PathBuf,
    address: String,
    version: Arc<Mutex<String>>,
    resource_patch: Arc<Mutex<serde_json::Value>>,
    is_held: Arc<AtomicBool>,
    request_count: Arc<AtomicUsize>,
    is_stopping: Arc<AtomicBool>,
    worker: Option<thread::JoinHandle<()>>,
}
impl ResourceServer {
    fn start_resource_server() -> Self {
        let root =
            std::env::temp_dir().join(format!("shikigen-file-open-{}", uuid::Uuid::new_v4()));
        fs::create_dir(&root).unwrap();
        fs::write(root.join("report.txt"), "本地报告").unwrap();
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let address = format!("http://{}", listener.local_addr().unwrap());
        let version = Arc::new(Mutex::new("version-1".to_string()));
        let resource_patch = Arc::new(Mutex::new(serde_json::json!({})));
        let is_held = Arc::new(AtomicBool::new(false));
        let request_count = Arc::new(AtomicUsize::new(0));
        let is_stopping = Arc::new(AtomicBool::new(false));
        let server_root = root.clone();
        let server_version = version.clone();
        let server_patch = resource_patch.clone();
        let is_server_held = is_held.clone();
        let server_count = request_count.clone();
        let is_server_stopping = is_stopping.clone();
        let worker = thread::spawn(move || {
            for stream in listener.incoming() {
                if is_server_stopping.load(Ordering::SeqCst) {
                    break;
                }
                let mut stream = stream.unwrap();
                stream
                    .set_read_timeout(Some(Duration::from_secs(2)))
                    .unwrap();
                let mut request = String::new();
                BufReader::new(&mut stream).read_line(&mut request).unwrap();
                assert!(request.starts_with("GET "), "resource queries never write");
                server_count.fetch_add(1, Ordering::SeqCst);
                while is_server_held.load(Ordering::SeqCst)
                    && !is_server_stopping.load(Ordering::SeqCst)
                {
                    thread::sleep(Duration::from_millis(2));
                }
                let payload = if request.starts_with("GET /api/workspace ") {
                    serde_json::json!({"data":{"workspace_id":"workspace-1","root":server_root}})
                } else {
                    let mut resource = serde_json::json!({
                        "workspace_id":"workspace-1","resource_id":"resource-1",
                        "absolute_path":server_root.join("report.txt"),"relative_path":"report.txt",
                        "name":"report.txt","kind":"file","mime_type":"text/plain","size":12,
                        "modified_at":"2026-10-06T00:00:00Z","version":*server_version.lock().unwrap(),"can_preview":false
                    });
                    for (key,value) in server_patch.lock().unwrap().as_object().unwrap() {resource[key]=value.clone();}
                    serde_json::json!({"data":resource})
                }.to_string();
                write!(stream,"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",payload.len(),payload).unwrap();
            }
        });
        Self {
            root,
            address,
            version,
            resource_patch,
            is_held,
            request_count,
            is_stopping,
            worker: Some(worker),
        }
    }
    fn read_backend_snapshot(&self) -> BackendSnapshot {
        BackendSnapshot {
            state: "ready".into(),
            revision: 1,
            startup_id: Some("startup-1".into()),
            base_url: Some(self.address.clone()),
            can_retry: false,
            error: None,
        }
    }
}
impl Drop for ResourceServer {
    fn drop(&mut self) {
        self.is_stopping.store(true, Ordering::SeqCst);
        self.is_held.store(false, Ordering::SeqCst);
        let _ = TcpStream::connect(self.address.trim_start_matches("http://"));
        self.worker.take().unwrap().join().unwrap();
        fs::remove_dir_all(&self.root).unwrap();
    }
}

#[test]
fn cancellation_replacement_and_host_invalidation_never_reuse_old_confirmation() {
    let server = ResourceServer::start_resource_server();
    let startup_snapshot = server.read_backend_snapshot();
    let intents = WorkspaceFileOpens::new(Arc::new(move || startup_snapshot.clone())).unwrap();
    let cancelled_confirmation = intents
        .prepare_file_open("main", "startup-1", "report.txt")
        .unwrap();
    assert!(intents
        .discard_file_intent("main", &cancelled_confirmation.request_id)
        .unwrap());
    assert_eq!(
        intents
            .open_prepared_file("main", &cancelled_confirmation.request_id, |_| panic!(
                "cancelled_confirmation"
            ))
            .unwrap_err()
            .code,
        "invalid_file_intent"
    );
    let older_confirmation = intents
        .prepare_file_open("main", "startup-1", "report.txt")
        .unwrap();
    let newer_confirmation = intents
        .prepare_file_open("main", "startup-1", "report.txt")
        .unwrap();
    assert_ne!(older_confirmation.request_id, newer_confirmation.request_id);
    assert!(!intents
        .discard_file_intent("main", &older_confirmation.request_id)
        .unwrap());
    assert_eq!(
        intents
            .open_prepared_file("main", &older_confirmation.request_id, |_| panic!(
                "replaced"
            ))
            .unwrap_err()
            .code,
        "invalid_file_intent"
    );
    intents.invalidate_file_intents();
    assert_eq!(
        intents
            .open_prepared_file("main", &newer_confirmation.request_id, |_| panic!("hidden"))
            .unwrap_err()
            .code,
        "invalid_file_intent"
    );
}

#[test]
fn intent_expires_at_exactly_five_minutes_without_sleeping() {
    let server = ResourceServer::start_resource_server();
    let startup_snapshot = server.read_backend_snapshot();
    let clock = Arc::new(Mutex::new(Instant::now()));
    let clock_state = clock.clone();
    let intents = WorkspaceFileOpens::with_clock(
        Arc::new(move || startup_snapshot.clone()),
        Arc::new(move || *clock_state.lock().unwrap()),
    )
    .unwrap();
    let intent = intents
        .prepare_file_open("main", "startup-1", "report.txt")
        .unwrap();
    *clock.lock().unwrap() += Duration::from_secs(300);
    assert_eq!(
        intents
            .open_prepared_file("main", &intent.request_id, |_| panic!("expired"))
            .unwrap_err()
            .code,
        "expired_file_intent"
    );
    let next_confirmation = intents
        .prepare_file_open("main", "startup-1", "report.txt")
        .unwrap();
    *clock.lock().unwrap() += Duration::from_secs(299);
    assert!(intents
        .open_prepared_file("main", &next_confirmation.request_id, |_| Ok(()))
        .unwrap());
}

#[test]
fn non_main_window_old_startup_and_non_host_address_are_rejected_before_query() {
    let server = ResourceServer::start_resource_server();
    let startup_snapshot = Arc::new(Mutex::new(server.read_backend_snapshot()));
    let snapshot_state = startup_snapshot.clone();
    let intents =
        WorkspaceFileOpens::new(Arc::new(move || snapshot_state.lock().unwrap().clone())).unwrap();
    assert_eq!(
        intents
            .prepare_file_open("other", "startup-1", "report.txt")
            .unwrap_err()
            .code,
        "invalid_window"
    );
    assert_eq!(
        intents
            .prepare_file_open("main", "old-startup", "report.txt")
            .unwrap_err()
            .code,
        "stale_backend_lease"
    );
    startup_snapshot.lock().unwrap().base_url = Some("https://example.org:443".into());
    assert_eq!(
        intents
            .prepare_file_open("main", "startup-1", "report.txt")
            .unwrap_err()
            .code,
        "stale_backend_lease"
    );
    assert_eq!(server.request_count.load(Ordering::SeqCst), 0);
}

#[test]
fn changed_version_requires_a_new_confirmation_and_system_failure_is_consumed() {
    let server = ResourceServer::start_resource_server();
    let startup_snapshot = server.read_backend_snapshot();
    let intents = WorkspaceFileOpens::new(Arc::new(move || startup_snapshot.clone())).unwrap();
    let intent = intents
        .prepare_file_open("main", "startup-1", "report.txt")
        .unwrap();
    *server.version.lock().unwrap() = "version-2".into();
    assert_eq!(
        intents
            .open_prepared_file("main", &intent.request_id, |_| panic!("changed"))
            .unwrap_err()
            .code,
        "changed_file_target"
    );
    let next_confirmation = intents
        .prepare_file_open("main", "startup-1", "report.txt")
        .unwrap();
    let rejection = intents
        .open_prepared_file("main", &next_confirmation.request_id, |_| {
            Err("系统没有默认程序（1155）".into())
        })
        .unwrap_err();
    assert_eq!(rejection.code, "file_open_failed");
    assert_eq!(rejection.message, "系统没有默认程序（1155）");
    assert_eq!(
        intents
            .open_prepared_file("main", &next_confirmation.request_id, |_| panic!(
                "no retry"
            ))
            .unwrap_err()
            .code,
        "invalid_file_intent"
    );
}

#[test]
fn native_filesystem_independently_rejects_directory_and_outside_target_metadata() {
    let server = ResourceServer::start_resource_server();
    let startup_snapshot = server.read_backend_snapshot();
    let intents = WorkspaceFileOpens::new(Arc::new(move || startup_snapshot.clone())).unwrap();
    *server.resource_patch.lock().unwrap() = serde_json::json!({"absolute_path":server.root});
    assert_eq!(
        intents
            .prepare_file_open("main", "startup-1", "report.txt")
            .unwrap_err()
            .code,
        "invalid_resource"
    );
    let outside = server.root.with_extension("outside.txt");
    fs::write(&outside, "outside").unwrap();
    *server.resource_patch.lock().unwrap() = serde_json::json!({"absolute_path":outside});
    let result = intents.prepare_file_open("main", "startup-1", "report.txt");
    fs::remove_file(outside).unwrap();
    assert_eq!(result.unwrap_err().code, "invalid_resource");
    *server.resource_patch.lock().unwrap() = serde_json::json!({"workspace_id":"other-workspace"});
    assert_eq!(
        intents
            .prepare_file_open("main", "startup-1", "report.txt")
            .unwrap_err()
            .code,
        "invalid_resource"
    );
}

#[test]
fn revoked_lease_cannot_open_even_when_old_http_endpoint_still_responds() {
    let server = ResourceServer::start_resource_server();
    let startup_snapshot = Arc::new(Mutex::new(server.read_backend_snapshot()));
    let snapshot_state = startup_snapshot.clone();
    let intents =
        WorkspaceFileOpens::new(Arc::new(move || snapshot_state.lock().unwrap().clone())).unwrap();
    let intent = intents
        .prepare_file_open("main", "startup-1", "report.txt")
        .unwrap();
    startup_snapshot.lock().unwrap().startup_id = Some("startup-2".into());
    assert_eq!(
        intents
            .open_prepared_file("main", &intent.request_id, |_| panic!("old host"))
            .unwrap_err()
            .code,
        "stale_backend_lease"
    );
}

#[test]
fn concurrent_confirmation_opens_at_most_once() {
    let server = ResourceServer::start_resource_server();
    let startup_snapshot = server.read_backend_snapshot();
    let intents =
        Arc::new(WorkspaceFileOpens::new(Arc::new(move || startup_snapshot.clone())).unwrap());
    let intent = intents
        .prepare_file_open("main", "startup-1", "report.txt")
        .unwrap();
    let opens = Arc::new(AtomicUsize::new(0));
    let mut workers = vec![];
    for _ in 0..2 {
        let intents = intents.clone();
        let request_id = intent.request_id.clone();
        let opens = opens.clone();
        workers.push(thread::spawn(move || {
            intents.open_prepared_file("main", &request_id, |_| {
                opens.fetch_add(1, Ordering::SeqCst);
                Ok(())
            })
        }));
    }
    let results: Vec<_> = workers
        .into_iter()
        .map(|worker| worker.join().unwrap())
        .collect();
    assert_eq!(results.iter().filter(|result| result.is_ok()).count(), 1);
    assert_eq!(opens.load(Ordering::SeqCst), 1);
}

#[test]
fn close_during_final_resource_query_prevents_dispatch_and_locks_windows_file() {
    let server = ResourceServer::start_resource_server();
    let startup_snapshot = server.read_backend_snapshot();
    let intents =
        Arc::new(WorkspaceFileOpens::new(Arc::new(move || startup_snapshot.clone())).unwrap());
    let intent = intents
        .prepare_file_open("main", "startup-1", "report.txt")
        .unwrap();
    server.is_held.store(true, Ordering::SeqCst);
    let current_intents = intents.clone();
    let request_id = intent.request_id.clone();
    let open_invocation = thread::spawn(move || {
        current_intents
            .open_prepared_file("main", &request_id, |_| panic!("closed before dispatch"))
    });
    let deadline = Instant::now() + Duration::from_secs(2);
    while server.request_count.load(Ordering::SeqCst) < 3 {
        assert!(Instant::now() < deadline);
        thread::sleep(Duration::from_millis(2));
    }
    #[cfg(windows)]
    assert!(fs::write(server.root.join("report.txt"), "changed while checked").is_err());
    assert!(intents
        .discard_file_intent("main", &intent.request_id)
        .unwrap());
    server.is_held.store(false, Ordering::SeqCst);
    assert_eq!(
        open_invocation.join().unwrap().unwrap_err().code,
        "stale_file_intent"
    );
}

#[test]
fn host_invalidation_never_waits_for_the_os_dispatch_callback() {
    let server = ResourceServer::start_resource_server();
    let startup_snapshot = server.read_backend_snapshot();
    let intents =
        Arc::new(WorkspaceFileOpens::new(Arc::new(move || startup_snapshot.clone())).unwrap());
    let confirmation = intents
        .prepare_file_open("main", "startup-1", "report.txt")
        .unwrap();
    let (announce_dispatch, await_dispatch) = mpsc::channel();
    let (release_dispatch, await_release) = mpsc::channel();
    let current_intents = intents.clone();
    let request_id = confirmation.request_id.clone();
    let open_invocation = thread::spawn(move || {
        current_intents.open_prepared_file("main", &request_id, |_| {
            announce_dispatch.send(()).unwrap();
            await_release.recv().unwrap();
            Ok(())
        })
    });
    await_dispatch.recv_timeout(Duration::from_secs(2)).unwrap();
    let (announce_invalidation, await_invalidation) = mpsc::channel();
    let current_intents = intents.clone();
    let invalidation_invocation = thread::spawn(move || {
        current_intents.invalidate_file_intents();
        announce_invalidation.send(()).unwrap();
    });
    let invalidation_result = await_invalidation.recv_timeout(Duration::from_secs(2));
    // Always release and join before asserting, including a failing old implementation.
    release_dispatch.send(()).unwrap();
    assert!(open_invocation.join().unwrap().unwrap());
    invalidation_invocation.join().unwrap();
    assert!(
        invalidation_result.is_ok(),
        "host invalidation waited for OS dispatch"
    );
    assert_eq!(
        intents
            .open_prepared_file("main", &confirmation.request_id, |_| panic!("never repeat"))
            .unwrap_err()
            .code,
        "invalid_file_intent"
    );
}

#[test]
fn preparation_never_opens_and_one_confirmation_is_consumed_once() {
    let server = ResourceServer::start_resource_server();
    let startup_snapshot = server.read_backend_snapshot();
    let intents = WorkspaceFileOpens::new(Arc::new(move || startup_snapshot.clone())).unwrap();
    let intent = intents
        .prepare_file_open("main", "startup-1", "report.txt")
        .unwrap();
    assert_eq!(intent.resource.name, "report.txt");
    assert_eq!(
        intent.resource.absolute_path,
        server.root.join("report.txt").to_str().unwrap()
    );
    assert!(intents
        .open_prepared_file("main", &intent.request_id, |path| {
            assert_eq!(path, server.root.join("report.txt"));
            Ok(())
        })
        .unwrap());
    assert_eq!(
        intents
            .open_prepared_file("main", &intent.request_id, |_| panic!("never reopen"))
            .unwrap_err()
            .code,
        "invalid_file_intent"
    );
}
