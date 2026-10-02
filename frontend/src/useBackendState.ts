import { useEffect, useRef, useState } from "react";
import { invoke, isTauri } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { subscribeBackendState, type BackendSnapshot, type BackendSubscription, type RetryResult } from "./backend-state";
import { BackendClient } from "./backend-client";

export function useBackendState() {
  const desktop = isTauri();
  const [client] = useState(() => new BackendClient());
  const [snapshot, setSnapshot] = useState<BackendSnapshot | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [retrying, setRetrying] = useState(false);
  const [retryError, setRetryError] = useState<string | null>(null);
  const subscription = useRef<BackendSubscription | null>(null);
  useEffect(() => {
    if (!desktop) return;
    const current = subscribeBackendState({
      listen: (receive) => listen<BackendSnapshot>("backend-state-changed", event => receive(event.payload)),
      query: () => invoke<BackendSnapshot>("get_backend_state"),
      retry: () => invoke<RetryResult>("retry_backend"),
    }, value => {
      client.update(value);
      setSnapshot(value);
      setError(null);
      setRetryError(null);
    }, error => { client.update(null); setError(String(error)); });
    subscription.current = current;
    return () => { subscription.current = null; current.dispose(); client.update(null); };
  }, [desktop, client]);
  async function retry() {
    const current = subscription.current;
    if (!current || retrying) return;
    setRetrying(true);
    setRetryError(null);
    try {
      const result = await current.retry();
      if (subscription.current === current && result && !result.accepted) {
        setRetryError(result.reason ?? "当前状态不能重试");
      }
    } catch (error) {
      if (subscription.current === current) setRetryError(`无法请求重试：${String(error)}`);
    } finally {
      if (subscription.current === current) setRetrying(false);
    }
  }
  return { desktop, snapshot, error, retry, retrying, retryError, session: client.session };
}
