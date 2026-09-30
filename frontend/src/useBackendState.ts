import { useEffect, useState } from "react";
import { invoke, isTauri } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { subscribeBackendState, type BackendSnapshot } from "./backend-state";

export function useBackendState() {
  const desktop = isTauri();
  const [snapshot, setSnapshot] = useState<BackendSnapshot | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (!desktop) return;
    return subscribeBackendState({
      listen: (receive) => listen<BackendSnapshot>("backend-state-changed", event => receive(event.payload)),
      query: () => invoke<BackendSnapshot>("get_backend_state"),
    }, setSnapshot, error => setError(String(error)));
  }, [desktop]);
  return { desktop, snapshot, error };
}
