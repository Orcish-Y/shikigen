use crate::backend::BackendSnapshot;
use serde::{de::DeserializeOwned, Deserialize, Serialize};
use std::{
    collections::HashMap,
    fs::{self, File, OpenOptions},
    io::Read,
    path::{Path, PathBuf},
    sync::{Arc, Mutex},
    time::{Duration, Instant},
};

const INTENT_LIFETIME: Duration = Duration::from_secs(300);
const RESPONSE_LIMIT: u64 = 64 * 1024;
type ReadLeaseFn = Arc<dyn Fn() -> BackendSnapshot + Send + Sync>;
type ReadClockFn = Arc<dyn Fn() -> Instant + Send + Sync>;

#[derive(Debug, Serialize)]
pub struct WorkspaceFileError {
    pub code: &'static str,
    pub message: String,
}
impl std::fmt::Display for WorkspaceFileError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(formatter, "{}: {}", self.code, self.message)
    }
}
impl std::error::Error for WorkspaceFileError {}
fn create_file_error(code: &'static str, message: impl Into<String>) -> WorkspaceFileError {
    WorkspaceFileError {
        code,
        message: message.into(),
    }
}
#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
pub struct FileResource {
    pub workspace_id: String,
    pub resource_id: String,
    pub absolute_path: String,
    pub relative_path: String,
    pub name: String,
    pub kind: String,
    pub mime_type: Option<String>,
    pub size: u64,
    pub modified_at: String,
    pub version: String,
    pub can_preview: bool,
}
#[derive(Clone, Debug, Serialize)]
pub struct PreparedFileOpen {
    pub request_id: String,
    pub startup_id: String,
    pub workspace_root: String,
    #[serde(flatten)]
    pub resource: FileResource,
}
#[derive(Deserialize)]
struct WorkspaceIdentity {
    workspace_id: String,
    root: String,
}
#[derive(Deserialize)]
struct QueryResponse<T> {
    data: T,
}
#[derive(Clone, PartialEq)]
struct AddressLease {
    startup_id: String,
    base_url: String,
}
struct FileIntent {
    confirmation: PreparedFileOpen,
    reference: String,
    lease: AddressLease,
    expires_at: Instant,
    epoch: u64,
}
#[derive(Default)]
struct IntentLedger {
    epoch: u64,
    requests: HashMap<String, FileIntent>,
    active_request_id: Option<String>,
}

/// Native ownership of one-use intentions. HTTP, time and OS opening are
/// external seams; caller-provided addresses/roots are never accepted.
pub struct WorkspaceFileOpens {
    read_lease: ReadLeaseFn,
    read_clock: ReadClockFn,
    client: reqwest::blocking::Client,
    ledger: Mutex<IntentLedger>,
}
impl WorkspaceFileOpens {
    pub fn new(read_lease: ReadLeaseFn) -> Result<Self, WorkspaceFileError> {
        Self::with_clock(read_lease, Arc::new(Instant::now))
    }
    pub fn with_clock(
        read_lease: ReadLeaseFn,
        read_clock: ReadClockFn,
    ) -> Result<Self, WorkspaceFileError> {
        let client = reqwest::blocking::Client::builder()
            .no_proxy()
            .redirect(reqwest::redirect::Policy::none())
            .timeout(Duration::from_secs(5))
            .build()
            .map_err(|error| create_file_error("resource_query_failed", error.to_string()))?;
        Ok(Self {
            read_lease,
            read_clock,
            client,
            ledger: Mutex::default(),
        })
    }
    pub fn invalidate_file_intents(&self) {
        let mut ledger = self.ledger.lock().unwrap();
        ledger.epoch += 1;
        ledger.requests.clear();
        ledger.active_request_id = None;
    }
    pub fn discard_file_intent(
        &self,
        window: &str,
        request_id: &str,
    ) -> Result<bool, WorkspaceFileError> {
        validate_window(window)?;
        let mut ledger = self.ledger.lock().unwrap();
        if ledger.active_request_id.as_deref() != Some(request_id) {
            return Ok(false);
        }
        ledger.requests.remove(request_id);
        ledger.active_request_id = None;
        ledger.epoch += 1;
        Ok(true)
    }
    fn read_current_lease(&self, startup_id: &str) -> Result<AddressLease, WorkspaceFileError> {
        let snapshot = (self.read_lease)();
        if snapshot.state != "ready" || snapshot.startup_id.as_deref() != Some(startup_id) {
            return Err(create_file_error(
                "stale_backend_lease",
                "后端启动身份已失效，请重新准备文件打开",
            ));
        }
        let base_url = snapshot
            .base_url
            .ok_or_else(|| create_file_error("stale_backend_lease", "后端地址已失效"))?;
        let address = url::Url::parse(&base_url)
            .map_err(|_| create_file_error("stale_backend_lease", "宿主地址无效"))?;
        if address.scheme() != "http"
            || address.host_str() != Some("127.0.0.1")
            || address.port().is_none()
            || address.path() != "/"
            || address.query().is_some()
            || address.fragment().is_some()
            || !address.username().is_empty()
            || address.password().is_some()
        {
            return Err(create_file_error(
                "stale_backend_lease",
                "宿主地址不是自管本地后端",
            ));
        }
        Ok(AddressLease {
            startup_id: startup_id.into(),
            base_url,
        })
    }
    fn query_resource<T: DeserializeOwned>(&self, address: &str) -> Result<T, WorkspaceFileError> {
        let mut response = self
            .client
            .get(address)
            .header("Cache-Control", "no-store")
            .send()
            .map_err(|error| create_file_error("resource_query_failed", error.to_string()))?;
        let status = response.status();
        let mut body = Vec::new();
        response
            .by_ref()
            .take(RESPONSE_LIMIT + 1)
            .read_to_end(&mut body)
            .map_err(|error| create_file_error("resource_query_failed", error.to_string()))?;
        if body.len() as u64 > RESPONSE_LIMIT {
            return Err(create_file_error(
                "resource_query_failed",
                "资源响应过大，无法核实",
            ));
        }
        if !status.is_success() {
            return Err(create_file_error(
                "resource_query_failed",
                format!("HTTP {status}: {}", String::from_utf8_lossy(&body)),
            ));
        }
        serde_json::from_slice::<QueryResponse<T>>(&body)
            .map(|response| response.data)
            .map_err(|error| {
                create_file_error("invalid_resource", format!("资源响应无法解析：{error}"))
            })
    }
    fn resolve_file(
        &self,
        lease: &AddressLease,
        reference: &str,
    ) -> Result<(String, FileResource), WorkspaceFileError> {
        let workspace: WorkspaceIdentity =
            self.query_resource(&format!("{}/api/workspace", lease.base_url))?;
        let mut address = url::Url::parse(&format!(
            "{}/api/workspace/resources/resolve",
            lease.base_url
        ))
        .unwrap();
        address.query_pairs_mut().append_pair("path", reference);
        let resource: FileResource = self.query_resource(address.as_str())?;
        if workspace.workspace_id.is_empty()
            || resource.workspace_id != workspace.workspace_id
            || resource.kind != "file"
            || resource.resource_id.is_empty()
            || resource.version.is_empty()
            || resource.name.is_empty()
            || resource.relative_path.is_empty()
            || resource.modified_at.is_empty()
        {
            return Err(create_file_error(
                "invalid_resource",
                "工作目录身份或文件元数据无效",
            ));
        }
        verify_native_target(&workspace.root, &resource.absolute_path)?;
        Ok((workspace.root, resource))
    }
    pub fn prepare_file_open(
        &self,
        window: &str,
        startup_id: &str,
        reference: &str,
    ) -> Result<PreparedFileOpen, WorkspaceFileError> {
        validate_window(window)?;
        let lease = self.read_current_lease(startup_id)?;
        // A fresh click replaces any older confirmation, including an in-flight preparation.
        let epoch = {
            let mut ledger = self.ledger.lock().unwrap();
            ledger.epoch += 1;
            ledger.requests.clear();
            ledger.active_request_id = None;
            ledger.epoch
        };
        let (workspace_root, resource) = self.resolve_file(&lease, reference)?;
        let current_address_lease = self.read_current_lease(startup_id)?;
        let mut ledger = self.ledger.lock().unwrap();
        if ledger.epoch != epoch || current_address_lease != lease {
            return Err(create_file_error(
                "stale_file_intent",
                "文件准备已失效，请重新点击",
            ));
        }
        let confirmation = PreparedFileOpen {
            request_id: uuid::Uuid::new_v4().to_string(),
            startup_id: startup_id.into(),
            workspace_root,
            resource,
        };
        let intent = FileIntent {
            confirmation: confirmation.clone(),
            reference: reference.into(),
            lease,
            expires_at: (self.read_clock)() + INTENT_LIFETIME,
            epoch,
        };
        ledger
            .requests
            .insert(confirmation.request_id.clone(), intent);
        ledger.active_request_id = Some(confirmation.request_id.clone());
        Ok(confirmation)
    }
    pub fn open_prepared_file(
        &self,
        window: &str,
        request_id: &str,
        perform_open: impl FnOnce(&Path) -> Result<(), String>,
    ) -> Result<bool, WorkspaceFileError> {
        validate_window(window)?;
        // Consume before querying or dispatching: failures and concurrent repeats need a new confirmation.
        let intent = self
            .ledger
            .lock()
            .unwrap()
            .requests
            .remove(request_id)
            .ok_or_else(|| {
                create_file_error(
                    "invalid_file_intent",
                    "本次文件确认已使用、关闭或失效，请重新准备",
                )
            })?;
        if (self.read_clock)() >= intent.expires_at {
            return Err(create_file_error(
                "expired_file_intent",
                "本次文件确认已超过五分钟，请重新准备",
            ));
        }
        if self.read_current_lease(&intent.lease.startup_id)? != intent.lease {
            return Err(create_file_error(
                "stale_backend_lease",
                "后端地址已变化，请重新准备",
            ));
        }
        let target = verify_native_target(
            &intent.confirmation.workspace_root,
            &intent.confirmation.resource.absolute_path,
        )?;
        // On Windows, prevent writes/replacement while final metadata is read and
        // the default program receives this same path. No shell is composed.
        let _file_guard = guard_file_target(&target)?;
        let (root, resource) = self.resolve_file(&intent.lease, &intent.reference)?;
        if root != intent.confirmation.workspace_root || resource != intent.confirmation.resource {
            return Err(create_file_error(
                "changed_file_target",
                "文件路径、版本或工作目录已变化，请重新准备并确认",
            ));
        }
        let ledger = self.ledger.lock().unwrap();
        if ledger.epoch != intent.epoch
            || (self.read_clock)() >= intent.expires_at
            || self.read_current_lease(&intent.lease.startup_id)? != intent.lease
        {
            return Err(create_file_error(
                "stale_file_intent",
                "本次确认已失效，请重新准备",
            ));
        }
        if verify_native_target(&root, &resource.absolute_path)? != target {
            return Err(create_file_error(
                "changed_file_target",
                "实际文件路径已变化，请重新准备并确认",
            ));
        }
        // Final authorization starts dispatch. Never hold the ledger while an
        // OS/Tauri callback waits on the UI thread: hiding or lease loss on that
        // thread must be able to invalidate other intentions without deadlock.
        // Once dispatch starts, closing cannot promise to undo the OS operation.
        drop(ledger);
        perform_open(Path::new(&resource.absolute_path))
            .map_err(|message| create_file_error("file_open_failed", message))?;
        Ok(true)
    }
}
fn validate_window(window: &str) -> Result<(), WorkspaceFileError> {
    if window != "main" {
        return Err(create_file_error(
            "invalid_window",
            "本地文件打开仅限主窗口",
        ));
    }
    Ok(())
}
fn verify_native_target(root: &str, path: &str) -> Result<PathBuf, WorkspaceFileError> {
    if !Path::new(root).is_absolute() || !Path::new(path).is_absolute() {
        return Err(create_file_error(
            "invalid_resource",
            "资源服务未返回完整本地路径",
        ));
    }
    let root = fs::canonicalize(root).map_err(|error| {
        create_file_error("invalid_resource", format!("工作目录不可用：{error}"))
    })?;
    let target = fs::canonicalize(path).map_err(|error| {
        create_file_error("invalid_resource", format!("本地文件不可用：{error}"))
    })?;
    if !root.is_dir() || !target.starts_with(&root) || !target.is_file() {
        return Err(create_file_error(
            "invalid_resource",
            "只支持当前工作目录内的普通文件，目录和越界链接不可打开",
        ));
    }
    Ok(target)
}
fn guard_file_target(target: &Path) -> Result<File, WorkspaceFileError> {
    let mut options = OpenOptions::new();
    options.read(true);
    #[cfg(windows)]
    {
        use std::os::windows::fs::OpenOptionsExt;
        options.share_mode(1); // FILE_SHARE_READ; no replacement or writes during dispatch.
    }
    options
        .open(target)
        .map_err(|error| create_file_error("invalid_resource", format!("无法核实文件：{error}")))
}
