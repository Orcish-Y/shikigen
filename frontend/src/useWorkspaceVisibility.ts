import { useEffect, useState } from 'react';
import { invoke, isTauri } from '@tauri-apps/api/core';
import { listen } from '@tauri-apps/api/event';
import { subscribeWorkspaceVisibility, type WorkspaceVisibility } from './workspace-visibility';

export function useWorkspaceVisibility() {
  // 首次未知按可见处理；查询失败时不覆盖已知值。
  const [visible, setVisible] = useState(true);
  useEffect(() => {
    if (!isTauri()) return;
    const subscription = subscribeWorkspaceVisibility({
      listen:receive => listen<WorkspaceVisibility>('workspace-visibility-changed', event => receive(event.payload)),
      query:() => invoke<WorkspaceVisibility>('get_workspace_visibility'),
    }, snapshot => setVisible(snapshot.visible), () => {});
    return subscription.dispose;
  }, []);
  return visible;
}
