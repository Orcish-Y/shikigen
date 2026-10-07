use serde::Serialize;
use serde_json::Value;
use std::{
    fmt, fs,
    path::{Path, PathBuf},
};

#[derive(Clone, Debug, Serialize)]
pub struct BackendError {
    pub code: String,
    pub message: String,
}
impl BackendError {
    pub fn new(code: &str, message: impl Into<String>) -> Self {
        Self {
            code: code.into(),
            message: message.into(),
        }
    }
}
impl fmt::Display for BackendError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}", self.message)
    }
}
impl std::error::Error for BackendError {}

#[derive(Clone, Debug)]
pub struct BackendConfig {
    /// Starting point for the Python listener's ascending port search.
    pub start_port: u16,
    pub startup_timeout_seconds: f64,
    pub shutdown_timeout_seconds: f64,
}
impl BackendConfig {
    pub fn from_document(document: &str) -> Result<Self, BackendError> {
        let root: Value = serde_json::from_str(document)
            .map_err(|_| BackendError::new("config", "配置必须是有效 JSON（数值必须有限）"))?;
        let root = root
            .as_object()
            .ok_or_else(|| BackendError::new("config", "配置必须是对象"))?;
        let mut backend_config = Self {
            start_port: 43127,
            startup_timeout_seconds: 60.0,
            shutdown_timeout_seconds: 10.0,
        };
        if let Some(value) = root.get("backend") {
            let backend_fields = value
                .as_object()
                .ok_or_else(|| BackendError::new("config", "backend 必须是对象，不能为 null"))?;
            for (field_name, field_value) in backend_fields {
                let make_invalid_field_error =
                    || BackendError::new("config", format!("backend.{field_name}: 类型或取值无效"));
                match field_name.as_str() {
                    "port" => {
                        backend_config.start_port = field_value
                            .as_u64()
                            .and_then(|v| u16::try_from(v).ok())
                            .filter(|v| *v > 0)
                            .ok_or_else(make_invalid_field_error)?
                    }
                    "startup_timeout_seconds" | "shutdown_timeout_seconds" => {
                        let seconds = field_value
                            .as_f64()
                            .filter(|v| v.is_finite() && *v > 0.0)
                            .ok_or_else(make_invalid_field_error)?;
                        if field_name == "startup_timeout_seconds" {
                            backend_config.startup_timeout_seconds = seconds;
                        } else {
                            backend_config.shutdown_timeout_seconds = seconds;
                        }
                    }
                    _ => {
                        return Err(BackendError::new(
                            "config",
                            format!("backend.{field_name}: 未知字段"),
                        ))
                    }
                }
            }
        }
        Ok(backend_config)
    }
}

#[derive(Clone, Debug)]
pub struct LaunchPlan {
    pub root: PathBuf,
    pub python: PathBuf,
    pub config_path: PathBuf,
    pub config: BackendConfig,
}
impl LaunchPlan {
    pub fn development() -> Result<Self, BackendError> {
        let root = Path::new(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .and_then(Path::parent)
            .ok_or_else(|| {
                BackendError::new("project_path", "编译期项目路径无效，请重新构建桌面应用")
            })?;
        Self::from_root(root)
    }
    pub fn from_root(root: &Path) -> Result<Self, BackendError> {
        if !root.is_absolute()
            || !root.join("pyproject.toml").is_file()
            || !root.join("app/desktop.py").is_file()
        {
            return Err(BackendError::new(
                "project_path",
                format!(
                    "项目路径已失效：{}；移动项目后请重新构建桌面应用",
                    root.display()
                ),
            ));
        }
        let python = root.join(".venv/Scripts/python.exe");
        if !python.is_file() {
            return Err(BackendError::new(
                "environment",
                "缺少项目 Windows Python 环境，请在项目根目录先运行 uv sync",
            ));
        }
        let config_path = root.join("config.json");
        let document = fs::read_to_string(&config_path).map_err(|_| {
            BackendError::new("config", format!("无法读取配置：{}", config_path.display()))
        })?;
        Ok(Self {
            root: root.into(),
            python,
            config_path,
            config: BackendConfig::from_document(&document)?,
        })
    }
}

mod logs;
mod manager;
pub use logs::BackendLogs;
pub use manager::{BackendManager, BackendSnapshot, Launcher, PlanLoader, RetryResult};
