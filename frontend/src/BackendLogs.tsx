import { useEffect, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";

interface LogSnapshot {
  startup_id: string | null;
  text: string;
  retained_bytes: number;
  truncated: boolean;
  read_error: string | null;
}

/** Mount with startup_id as the key, so retries discard the entire old view. */
export function BackendLogs({ startupId }: { startupId: string }) {
  const [logs, setLogs] = useState<LogSnapshot | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const request = useRef(0);
  const pending = useRef(false);
  useEffect(() => () => { request.current++; }, []);

  async function read() {
    if (pending.current) return;
    pending.current = true;
    const current = ++request.current;
    setLoading(true);
    setError(null);
    try {
      const result = await invoke<LogSnapshot>("get_backend_logs");
      if (current !== request.current) return;
      if (result.startup_id !== startupId) {
        setLogs(null);
        setError("启动已变化，请重新读取日志。");
        return;
      }
      setLogs(result);
    } catch {
      if (current === request.current) setError("无法读取本次启动日志，请重试读取。");
    } finally {
      if (current === request.current) {
        pending.current = false;
        setLoading(false);
      }
    }
  }

  return (
    <section className="backend-logs" aria-label="本次启动日志">
      <button className="secondary-button" disabled={loading} onClick={() => void read()}>
        {loading ? "正在读取日志…" : logs || error ? "刷新日志" : "查看本次启动日志"}
      </button>
      {error && <p role="alert">{error}</p>}
      {logs && <>
        <p>启动标识：{logs.startup_id}</p>
        <p>{logs.truncated ? "仅显示最近 1 MiB 日志，较早内容已丢弃。" : "本次启动的日志快照。"} 退出应用后不保留。</p>
        {logs.read_error && <p role="alert">{logs.read_error}</p>}
        {logs.text ? <pre tabIndex={0}>{logs.text}</pre> : <p>本次启动暂无日志。</p>}
      </>}
    </section>
  );
}
