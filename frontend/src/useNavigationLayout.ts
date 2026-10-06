import { useLayoutEffect, useRef, useState } from 'react';
import { NavigationLayout } from './navigation-layout';

export function useNavigationLayout(onBreakpointChange: () => void) {
  const [layout] = useState(() => {
    let storage: Storage | undefined;
    try { storage = window.localStorage; } catch { /* Storage access itself can fail. */ }
    return new NavigationLayout(window.innerWidth, storage);
  });
  const [view, setView] = useState(() => layout.readView());
  const notifyBreakpointChange = useRef(onBreakpointChange);
  notifyBreakpointChange.current = onBreakpointChange;
  useLayoutEffect(() => {
    function resizeViewport() {
      const previousView = layout.readView();
      const nextView = layout.resizeViewport(window.innerWidth);
      if (previousView.breakpoint !== nextView.breakpoint) notifyBreakpointChange.current();
      if (previousView.breakpoint !== nextView.breakpoint || previousView.isCollapsed !== nextView.isCollapsed) setView(nextView);
    }
    window.addEventListener('resize', resizeViewport);
    return () => window.removeEventListener('resize', resizeViewport);
  }, [layout]);
  return {...view, toggleDesktopNavigation: () => setView(layout.toggleDesktopNavigation())};
}
