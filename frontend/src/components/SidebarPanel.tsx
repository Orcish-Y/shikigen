import type { ReactNode } from 'react';
import type { SidebarView } from '../navigation-layout';
import { Overlay } from './Overlay';

/** Both views stay mounted while switching tabs; only the foreground view is accessible. */
export function SidebarPanel({view, onSwitch, onClose, navigation, history}: {
  view: SidebarView;
  onSwitch: (view: SidebarView) => void;
  onClose: () => void;
  navigation: ReactNode;
  history: ReactNode;
}) {
  return <Overlay title="菜单" variant="sidebar" onClose={onClose}
    fallbackFocus=".history-toggle, .mobile-navigation, .navigation-heading button">
    <div className="sidebar-switch" aria-label="菜单视图">
      <button className="text-button" aria-pressed={view === 'history'} onClick={() => onSwitch('history')}>会话列表</button>
      <button className="text-button" aria-pressed={view === 'navigation'} onClick={() => onSwitch('navigation')}>主导航</button>
    </div>
    <div className="sidebar-view" hidden={view !== 'history'}>{history}</div>
    <div className="sidebar-view" hidden={view !== 'navigation'}>{navigation}</div>
  </Overlay>;
}
