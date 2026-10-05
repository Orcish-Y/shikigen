use serde::Serialize;
use url::Url;

#[derive(Debug, Serialize)]
pub struct WebOpenError {
    pub code: &'static str,
    pub message: String,
}

/// Public boundary: validate before delegating to the operating system opener.
/// The callback is also the test seam for rejection and operating system errors.
pub fn open_web_url(
    raw: &str,
    open: impl FnOnce(&str) -> Result<(), String>,
) -> Result<bool, WebOpenError> {
    let invalid = || WebOpenError {
        code: "invalid_web_url",
        message: "仅支持完整的 http／https 网页链接".into(),
    };
    if raw.trim() != raw || raw.chars().any(|c| c.is_control() || c == '\\') {
        return Err(invalid());
    }
    let parsed = Url::parse(raw).map_err(|_| invalid())?;
    if !matches!(parsed.scheme(), "http" | "https")
        || parsed.host_str().is_none()
        || !raw
            .to_ascii_lowercase()
            .starts_with(&format!("{}://", parsed.scheme()))
    {
        return Err(invalid());
    }
    open(parsed.as_str()).map_err(|message| WebOpenError {
        code: "web_open_failed",
        message,
    })?;
    Ok(true)
}
