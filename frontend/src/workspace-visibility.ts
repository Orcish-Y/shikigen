export interface WorkspaceVisibility { revision:number; visible:boolean }
export interface VisibilityBridge {
  listen:(receive:(snapshot:WorkspaceVisibility) => void) => Promise<() => void>;
  query:() => Promise<WorkspaceVisibility>;
}

/** 可见性独立于后端 startup_id；订阅在查询前建立，旧查询不能覆盖新事件。 */
export function subscribeWorkspaceVisibility(
  bridge:VisibilityBridge,
  receive:(snapshot:WorkspaceVisibility) => void,
  onError:(error:unknown) => void,
) {
  let cancelled = false;
  let revision = -1;
  let unlisten:(() => void) | undefined;
  const accept = (snapshot:WorkspaceVisibility) => {
    if (cancelled || snapshot.revision <= revision) return;
    revision = snapshot.revision;
    receive(snapshot);
  };
  void (async () => {
    try {
      unlisten = await bridge.listen(accept);
      if (cancelled) {unlisten(); return;}
      accept(await bridge.query());
    } catch (error) {if (!cancelled) onError(error);}
  })();
  return {dispose:() => {cancelled = true; unlisten?.();}};
}
