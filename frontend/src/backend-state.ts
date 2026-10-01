export interface BackendSnapshot {
  state: "starting" | "ready" | "stopping" | "reclaiming" | "failed" | "stopped";
  revision: number;
  startup_id: string | null;
  base_url: string | null;
  can_retry: boolean;
  error: { code: string; message: string } | null;
}
export interface BackendBridge {
  listen: (receive: (snapshot: BackendSnapshot) => void) => Promise<() => void>;
  query: () => Promise<BackendSnapshot>;
  retry: () => Promise<RetryResult>;
}
export interface RetryResult {
  accepted: boolean;
  reason: string | null;
  snapshot: BackendSnapshot;
}
export interface BackendSubscription {
  dispose: () => void;
  retry: () => Promise<RetryResult | null>;
}

/** A page observes one existing host; subscribing never creates a backend. */
export function subscribeBackendState(
  bridge: BackendBridge,
  receive: (snapshot: BackendSnapshot) => void,
  onError: (error: unknown) => void,
): BackendSubscription {
  let cancelled = false;
  let revision = -1;
  let unlisten: (() => void) | undefined;
  const accept = (snapshot: BackendSnapshot) => {
    if (cancelled || snapshot.revision <= revision) return;
    revision = snapshot.revision;
    receive(snapshot);
  };
  void (async () => {
    try {
      unlisten = await bridge.listen(accept);
      if (cancelled) { unlisten(); return; }
      accept(await bridge.query());
    } catch (error) {
      if (!cancelled) onError(error);
    }
  })();
  return {
    dispose: () => { cancelled = true; unlisten?.(); },
    retry: async () => {
      if (cancelled) return null;
      const result = await bridge.retry();
      // Events, queries and command replies share the host's revision order.
      if (cancelled || result.snapshot.revision < revision) return null;
      accept(result.snapshot);
      return result;
    },
  };
}
