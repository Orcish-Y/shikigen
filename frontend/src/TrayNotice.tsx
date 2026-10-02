import { useEffect, useState } from "react";
import { invoke, isTauri } from "@tauri-apps/api/core";

export function TrayNotice() {
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (!isTauri()) return;
    let disposed = false;
    // Tray creation is a one-time host operation; query again on page reload.
    invoke<string | null>("get_tray_error").then(
      value => { if (!disposed) setError(value); },
      error => { if (!disposed) setError(`无法读取托盘状态：${String(error)}`); },
    );
    return () => { disposed = true; };
  }, []);
  return error ? <aside className="tray-notice" role="alert">{error}</aside> : null;
}
