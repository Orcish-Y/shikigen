use serde::Serialize;
use std::{
    collections::VecDeque,
    fs::File,
    io::{self, Read},
    sync::{Arc, Mutex},
    thread,
};

const LOG_LIMIT: usize = 1024 * 1024;

#[derive(Clone, Debug, Serialize)]
pub struct BackendLogs {
    pub startup_id: Option<String>,
    pub text: String,
    pub retained_bytes: usize,
    pub truncated: bool,
    pub read_error: Option<String>,
}

struct Tail {
    bytes: VecDeque<u8>,
    truncated: bool,
    read_error: Option<String>,
}

/// One attempt owns one buffer. Old drainers can never reach a new attempt.
pub(super) struct StartupLogs {
    startup_id: Option<String>,
    tail: Mutex<Tail>,
}

impl StartupLogs {
    pub fn new(startup_id: Option<String>) -> Self {
        Self {
            startup_id,
            tail: Mutex::new(Tail {
                bytes: VecDeque::with_capacity(LOG_LIMIT),
                truncated: false,
                read_error: None,
            }),
        }
    }

    pub fn snapshot(&self) -> BackendLogs {
        // Decode outside the buffer lock; no lifecycle operation waits for this.
        let (bytes, truncated, read_error) = {
            let tail = self.tail.lock().unwrap_or_else(|e| e.into_inner());
            (
                tail.bytes.iter().copied().collect::<Vec<_>>(),
                tail.truncated,
                tail.read_error.clone(),
            )
        };
        BackendLogs {
            startup_id: self.startup_id.clone(),
            text: String::from_utf8_lossy(&bytes).into_owned(),
            retained_bytes: bytes.len(),
            truncated,
            read_error,
        }
    }

    pub fn drain(self: &Arc<Self>, mut stderr: File) {
        let logs = Arc::downgrade(self);
        thread::spawn(move || {
            let mut bytes = [0; 8192];
            loop {
                match stderr.read(&mut bytes) {
                    Ok(0) => break,
                    Ok(count) => {
                        // Keep draining a late old pipe without retaining its cache.
                        let Some(logs) = logs.upgrade() else {
                            continue;
                        };
                        let mut tail = logs.tail.lock().unwrap_or_else(|e| e.into_inner());
                        let remove = (tail.bytes.len() + count).saturating_sub(LOG_LIMIT);
                        tail.truncated |= remove > 0;
                        tail.bytes.drain(..remove);
                        tail.bytes.extend(&bytes[..count]);
                    }
                    Err(error) if error.kind() == io::ErrorKind::Interrupted => continue,
                    Err(_) => {
                        if let Some(logs) = logs.upgrade() {
                            logs.tail
                                .lock()
                                .unwrap_or_else(|e| e.into_inner())
                                .read_error = Some("读取后端日志管道失败，日志可能不完整".into());
                        }
                        break;
                    }
                }
            }
        });
    }
}
