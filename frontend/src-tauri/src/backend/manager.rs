use super::{BackendError, LaunchPlan};
use crate::process::{ManagedProcess, SpawnSpec};
use serde::Serialize;
use serde_json::{json, Value};
use std::{
    collections::VecDeque,
    fs::File,
    io::{BufRead, BufReader, Read, Write},
    sync::{
        atomic::{AtomicBool, Ordering},
        mpsc::{self, Receiver, RecvTimeoutError},
        Arc, Mutex,
    },
    thread,
    time::{Duration, Instant},
};

const LINE_LIMIT: usize = 64 * 1024;
const LOG_LIMIT: usize = 64 * 1024;
#[derive(Clone, Debug, Serialize)]
pub struct BackendSnapshot {
    pub state: String,
    pub revision: u64,
    pub startup_id: Option<String>,
    pub base_url: Option<String>,
    pub can_retry: bool,
    pub error: Option<BackendError>,
}
impl BackendSnapshot {
    fn starting(revision: u64) -> Self {
        Self {
            state: "starting".into(),
            revision,
            startup_id: Some(uuid::Uuid::new_v4().to_string()),
            base_url: None,
            can_retry: false,
            error: None,
        }
    }
}
pub type Launcher =
    Arc<dyn Fn(&SpawnSpec) -> std::io::Result<Box<dyn ManagedProcess>> + Send + Sync>;
pub type PlanLoader = Arc<dyn Fn() -> Result<LaunchPlan, BackendError> + Send + Sync>;
#[derive(Clone, Debug, Serialize)]
pub struct RetryResult {
    pub accepted: bool,
    pub reason: Option<String>,
    pub snapshot: BackendSnapshot,
}
struct ManagerState {
    snapshot: BackendSnapshot,
    shutdown_at: Option<Instant>,
    released: bool,
}
pub struct BackendManager {
    state: Mutex<ManagerState>,
    stop: AtomicBool,
    load_plan: PlanLoader,
    launcher: Launcher,
    publish: Arc<dyn Fn(BackendSnapshot) + Send + Sync>,
}
impl BackendManager {
    /// Called once by host setup. Each accepted attempt loads its own plan.
    pub fn start(
        load_plan: PlanLoader,
        launcher: Launcher,
        publish: Arc<dyn Fn(BackendSnapshot) + Send + Sync>,
    ) -> Arc<Self> {
        let manager = Arc::new(Self {
            state: Mutex::new(ManagerState {
                snapshot: BackendSnapshot::starting(1),
                shutdown_at: None,
                released: false,
            }),
            stop: AtomicBool::new(false),
            load_plan,
            launcher,
            publish,
        });
        manager.launch(manager.snapshot().startup_id.unwrap());
        manager
    }
    fn launch(self: &Arc<Self>, id: String) {
        let worker = self.clone();
        thread::spawn(move || {
            if worker.stop.load(Ordering::SeqCst) {
                worker.finish(&id, None);
                return;
            }
            match (worker.load_plan)() {
                Err(error) => worker.finish(&id, Some(error)),
                Ok(plan) => worker.run(plan, &id),
            }
        });
    }
    pub fn retry(self: &Arc<Self>) -> RetryResult {
        let snapshot = {
            let mut current = self.state.lock().unwrap();
            let reason = if current.shutdown_at.is_some() {
                Some("应用正在退出，不能重试")
            } else if !current.released {
                Some("后端正在运行或尚未确认完全回收")
            } else if current.snapshot.state != "failed" || !current.snapshot.can_retry {
                Some("当前状态不能重试")
            } else {
                None
            };
            if let Some(reason) = reason {
                return RetryResult {
                    accepted: false,
                    reason: Some(reason.into()),
                    snapshot: current.snapshot.clone(),
                };
            }
            current.released = false;
            current.snapshot = BackendSnapshot::starting(current.snapshot.revision + 1);
            current.snapshot.clone()
        };
        (self.publish)(snapshot.clone());
        self.launch(snapshot.startup_id.clone().unwrap());
        RetryResult {
            accepted: true,
            reason: None,
            snapshot,
        }
    }
    pub fn snapshot(&self) -> BackendSnapshot {
        self.state.lock().unwrap().snapshot.clone()
    }
    /// Exit intent survives failed/unconfirmed reclamation; state alone cannot
    /// decide whether another desktop launch may activate the window.
    pub fn is_shutting_down(&self) -> bool {
        self.stop.load(Ordering::SeqCst)
    }
    pub fn request_shutdown(&self) {
        let snapshot = {
            let mut current = self.state.lock().unwrap();
            if current.shutdown_at.is_some() {
                return;
            }
            current.shutdown_at = Some(Instant::now());
            self.stop.store(true, Ordering::SeqCst);
            if current.released {
                current.snapshot.state = "stopped".into();
            } else if matches!(current.snapshot.state.as_str(), "starting" | "ready") {
                current.snapshot.state = "stopping".into();
            }
            current.snapshot.base_url = None;
            current.snapshot.can_retry = false;
            current.snapshot.revision += 1;
            current.snapshot.clone()
        };
        (self.publish)(snapshot);
    }
    /// Only called when there were no resources or both observations confirmed
    /// completion. Serialize completion with a possibly concurrent quit request.
    fn finish(&self, id: &str, error: Option<BackendError>) {
        let snapshot = {
            let mut current = self.state.lock().unwrap();
            if current.snapshot.startup_id.as_deref() != Some(id) {
                return;
            }
            current.released = true;
            current.snapshot.state = if current.shutdown_at.is_some() {
                "stopped"
            } else {
                "failed"
            }
            .into();
            current.snapshot.base_url = None;
            current.snapshot.can_retry = current.shutdown_at.is_none();
            current.snapshot.error = error;
            current.snapshot.revision += 1;
            current.snapshot.clone()
        };
        (self.publish)(snapshot);
    }
    fn transition(
        &self,
        id: &str,
        state: &str,
        base_url: Option<String>,
        error: Option<BackendError>,
    ) {
        let snapshot = {
            let mut current = self.state.lock().unwrap();
            // Serialize ready with shutdown requests through this same lock.
            if current.snapshot.startup_id.as_deref() != Some(id)
                || (state == "ready" && self.stop.load(Ordering::SeqCst))
            {
                return;
            }
            current.snapshot.revision += 1;
            current.snapshot.state = state.into();
            current.snapshot.base_url = base_url;
            current.snapshot.error = error;
            current.snapshot.can_retry = false;
            current.snapshot.clone()
        };
        (self.publish)(snapshot);
    }
    fn run(&self, plan: LaunchPlan, id: &str) {
        if self.stop.load(Ordering::SeqCst) {
            self.finish(id, None);
            return;
        }
        let started = Instant::now();
        let spec = SpawnSpec {
            executable: plan.python,
            cwd: plan.root,
            args: vec![
                "-m".into(),
                "app.desktop".into(),
                "--config".into(),
                plan.config_path.into_os_string(),
                "--startup-id".into(),
                id.into(),
                "--port".into(),
                plan.config.port.to_string().into(),
            ],
            env: vec![],
        };
        let mut process = match (self.launcher)(&spec) {
            Ok(value) => value,
            Err(error) => {
                self.finish(id, Some(BackendError::new("spawn", format!("无法启动项目 Python：{error}。请先在项目根目录运行 uv sync；移动项目后重新构建桌面应用"))));
                return;
            }
        };
        let Some(streams) = process.take_stdio() else {
            let error = BackendError::new("spawn", "平台未提供标准流");
            self.cleanup(
                process.as_ref(),
                None,
                id,
                plan.config.shutdown_timeout_seconds,
                Some(error),
            );
            return;
        };
        let mut input = streams.stdin;
        let messages = read_messages(streams.stdout);
        let logs = drain_logs(streams.stderr);
        let result = self.monitor(
            process.as_ref(),
            &messages,
            &logs,
            id,
            started,
            plan.config.startup_timeout_seconds,
        );
        // Drop the receiver before cleanup so a full bounded queue cannot retain
        // its reader thread. stderr continues draining throughout cleanup.
        drop(messages);
        self.cleanup(
            process.as_ref(),
            Some(&mut input),
            id,
            plan.config.shutdown_timeout_seconds,
            result.err(),
        );
    }
    fn monitor(
        &self,
        process: &dyn ManagedProcess,
        messages: &Receiver<Result<Value, BackendError>>,
        logs: &Mutex<VecDeque<u8>>,
        id: &str,
        started: Instant,
        timeout: f64,
    ) -> Result<(), BackendError> {
        let client = reqwest::blocking::Client::builder()
            .no_proxy()
            .redirect(reqwest::redirect::Policy::none())
            .build()
            .map_err(|e| BackendError::new("health", e.to_string()))?;
        let mut address = None;
        let mut ready = false;
        let mut probe_at = Instant::now();
        let mut exit_seen: Option<(Instant, u32)> = None;
        loop {
            if self.stop.load(Ordering::SeqCst) {
                return Ok(());
            }
            if !ready && started.elapsed().as_secs_f64() >= timeout {
                return Err(BackendError::new("startup_timeout", "后端启动超时"));
            }
            match messages.recv_timeout(Duration::from_millis(10)) {
                Ok(message) => {
                    let message = message?;
                    let message_id = message
                        .get("startup_id")
                        .and_then(Value::as_str)
                        .ok_or_else(|| protocol("缺少 startup_id"))?;
                    if message_id == id {
                        if message.get("version").and_then(Value::as_u64) != Some(1) {
                            return Err(protocol("控制协议版本无效"));
                        }
                        match message.get("type").and_then(Value::as_str) {
                            Some("bound") if address.is_none() => {
                                let port = message
                                    .get("port")
                                    .and_then(Value::as_u64)
                                    .filter(|v| *v > 0 && *v <= 65535)
                                    .ok_or_else(|| protocol("bound.port 无效"))?;
                                address = Some(format!("http://127.0.0.1:{port}"));
                                probe_at = Instant::now();
                            }
                            Some("startup_error") => {
                                let code = message
                                    .get("code")
                                    .and_then(Value::as_str)
                                    .ok_or_else(|| protocol("startup_error.code 无效"))?;
                                let detail = message
                                    .get("message")
                                    .and_then(Value::as_str)
                                    .ok_or_else(|| protocol("startup_error.message 无效"))?;
                                return Err(BackendError::new(code, detail));
                            }
                            _ => return Err(protocol("未知或重复控制消息")),
                        }
                    }
                }
                Err(RecvTimeoutError::Disconnected) => {
                    let tail: Vec<u8> = logs.lock().unwrap().iter().copied().collect();
                    return Err(BackendError::new(
                        "backend_exit",
                        format!(
                            "后端输出管道已关闭。缺少依赖时请在项目根目录运行 uv sync。\n{}",
                            String::from_utf8_lossy(&tail)
                        ),
                    ));
                }
                Err(RecvTimeoutError::Timeout) => {}
            }
            if let Some(code) = process
                .wait_exit(Duration::ZERO)
                .map_err(|e| BackendError::new("process_observation", e.to_string()))?
            {
                let (seen, _) = exit_seen.get_or_insert((Instant::now(), code));
                // Briefly drain already-written startup_error messages. A tool
                // retaining stdout must not hide its parent's death indefinitely.
                if ready || seen.elapsed() >= Duration::from_millis(50) {
                    let tail: Vec<u8> = logs.lock().unwrap().iter().copied().collect();
                    return Err(BackendError::new(
                        "backend_exit",
                        format!(
                            "后端意外退出（{code}）。缺少依赖时请先运行 uv sync。\n{}",
                            String::from_utf8_lossy(&tail)
                        ),
                    ));
                }
                continue;
            }
            if !ready && Instant::now() >= probe_at {
                if let Some(url) = &address {
                    let remaining = timeout - started.elapsed().as_secs_f64();
                    if remaining <= 0.0 {
                        continue;
                    }
                    let request_budget = Duration::from_secs_f64(remaining.min(1.0));
                    match probe(&client, url, id, request_budget)? {
                        true if !self.stop.load(Ordering::SeqCst)
                            && started.elapsed().as_secs_f64() < timeout =>
                        {
                            self.transition(id, "ready", Some(url.clone()), None);
                            ready = true;
                        }
                        _ => probe_at = Instant::now() + Duration::from_millis(250),
                    }
                }
            }
        }
    }
    fn cleanup(
        &self,
        process: &dyn ManagedProcess,
        input: Option<&mut File>,
        id: &str,
        timeout: f64,
        error: Option<BackendError>,
    ) {
        // One budget, including time already spent leaving a health probe.
        let started = self
            .state
            .lock()
            .unwrap()
            .shutdown_at
            .unwrap_or_else(Instant::now);
        self.transition(id, "stopping", None, error.clone());
        let mut exited = matches!(process.wait_exit(Duration::ZERO), Ok(Some(_)));
        if !exited {
            if let Some(input) = input {
                let _ = writeln!(
                    input,
                    "{}",
                    json!({"version":1,"startup_id":id,"type":"shutdown"})
                );
            }
            while started.elapsed().as_secs_f64() < timeout {
                let remaining = timeout - started.elapsed().as_secs_f64();
                if remaining <= 0.0 {
                    break;
                }
                match process.wait_exit(Duration::from_secs_f64(remaining.min(0.02))) {
                    Ok(Some(_)) => {
                        exited = true;
                        break;
                    }
                    Err(_) => break,
                    _ => {}
                }
            }
        }
        if !exited || !matches!(process.wait_tree_empty(Duration::ZERO), Ok(true)) {
            self.transition(id, "reclaiming", None, error.clone());
            let _ = process.terminate_tree();
        }
        let confirmation = Instant::now();
        let confirmed = loop {
            match (
                process.wait_tree_empty(Duration::ZERO),
                process.wait_exit(Duration::ZERO),
            ) {
                (Ok(true), Ok(Some(_))) => break true,
                (Err(_), _) | (_, Err(_)) => break false,
                _ if confirmation.elapsed() >= Duration::from_secs(5) => break false,
                _ => thread::sleep(Duration::from_millis(10)),
            }
        };
        if !confirmed {
            self.transition(
                id,
                "failed",
                None,
                Some(BackendError::new(
                    "reclamation_unconfirmed",
                    format!(
                        "无法确认后端已完全退出{}",
                        error
                            .as_ref()
                            .map(|e| format!("；原始错误：{}", e.message))
                            .unwrap_or_default()
                    ),
                )),
            );
            // Preserve ownership and keep retry disabled until both observations agree.
            loop {
                thread::sleep(Duration::from_millis(250));
                if matches!(process.wait_tree_empty(Duration::ZERO), Ok(true))
                    && matches!(process.wait_exit(Duration::ZERO), Ok(Some(_)))
                {
                    break;
                }
            }
        }
        self.finish(id, error);
    }
}
fn protocol(message: &str) -> BackendError {
    BackendError::new("protocol", message)
}
fn read_messages(output: File) -> Receiver<Result<Value, BackendError>> {
    let (sender, receiver) = mpsc::sync_channel(8);
    thread::spawn(move || {
        let mut reader = BufReader::new(output);
        loop {
            let mut line = Vec::new();
            let read = reader
                .by_ref()
                .take((LINE_LIMIT + 1) as u64)
                .read_until(b'\n', &mut line);
            if matches!(read, Ok(0)) {
                break;
            }
            let result = if read.is_err() {
                Err(protocol("读取控制管道失败"))
            } else if line.len() > LINE_LIMIT || line.last() != Some(&b'\n') {
                Err(protocol("控制消息超长或缺少换行"))
            } else {
                serde_json::from_slice(&line).map_err(|_| protocol("控制消息不是有效 JSON"))
            };
            let failed = result.is_err();
            if sender.send(result).is_err() || failed {
                break;
            }
        }
    });
    receiver
}
fn drain_logs(mut stderr: File) -> Arc<Mutex<VecDeque<u8>>> {
    let logs = Arc::new(Mutex::new(VecDeque::new()));
    let tail = logs.clone();
    thread::spawn(move || {
        let mut bytes = [0; 8192];
        while let Ok(count) = stderr.read(&mut bytes) {
            if count == 0 {
                break;
            }
            let mut tail = tail.lock().unwrap();
            let remove = (tail.len() + count).saturating_sub(LOG_LIMIT);
            tail.drain(..remove);
            tail.extend(&bytes[..count]);
        }
    });
    logs
}
fn probe(
    client: &reqwest::blocking::Client,
    url: &str,
    id: &str,
    budget: Duration,
) -> Result<bool, BackendError> {
    let mut response = match client
        .get(format!("{url}/health/ready"))
        .timeout(budget)
        .send()
    {
        Ok(response) => response,
        Err(e) if e.is_connect() || e.is_timeout() => return Ok(false),
        Err(e) => return Err(BackendError::new("health", format!("健康检查失败：{e}"))),
    };
    if response.status() == reqwest::StatusCode::SERVICE_UNAVAILABLE {
        return Ok(false);
    }
    if response.status() != reqwest::StatusCode::OK {
        return Err(BackendError::new("health", "健康检查 HTTP 状态无效"));
    }
    let mut bytes = Vec::new();
    if response
        .by_ref()
        .take((LINE_LIMIT + 1) as u64)
        .read_to_end(&mut bytes)
        .is_err()
    {
        // Transport/body timeouts are unready; the total deadline owns timeout.
        return Ok(false);
    }
    if bytes.len() > LINE_LIMIT {
        return Err(BackendError::new("health", "健康响应超长"));
    }
    let value: Value = serde_json::from_slice(&bytes)
        .map_err(|_| BackendError::new("health", "健康响应格式无效"))?;
    if value.get("version").and_then(Value::as_u64) != Some(1)
        || value.get("startup_id").and_then(Value::as_str) != Some(id)
        || value.get("status").and_then(Value::as_str) != Some("ready")
    {
        return Err(BackendError::new(
            "health_identity",
            "健康响应的启动标识、版本或状态不匹配",
        ));
    }
    Ok(true)
}
