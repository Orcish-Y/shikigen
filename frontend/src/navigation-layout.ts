export type NavigationBreakpoint = 'wide-desktop' | 'compact-desktop' | 'tablet' | 'phone';
export type SidebarView = 'history' | 'navigation';
export interface NavigationLayoutView {
  breakpoint: NavigationBreakpoint;
  isDesktop: boolean;
  isCollapsed: boolean;
}

export function calculateNavigationBreakpoint(width: number): NavigationBreakpoint {
  if (width >= 1440) return 'wide-desktop';
  if (width >= 1280) return 'compact-desktop';
  if (width >= 768) return 'tablet';
  return 'phone';
}

// The template wrote its defaults to the old key during initialization. Those
// records cannot establish an intentional desktop choice, so use a new version.
export const NAVIGATION_PREFERENCE_KEY = 'shikigen.desktop-navigation-collapsed.v1';
type PreferenceStorage = Pick<Storage, 'getItem' | 'setItem'>;

/** Only a deliberate desktop toggle writes storage. Resizing is a pure layout change. */
export class NavigationLayout {
  private width: number;
  private isCollapsedPreference: boolean | null = null;
  constructor(width: number, private storage?: PreferenceStorage) {
    this.width = width;
    try {
      const cachedPreference = storage?.getItem(NAVIGATION_PREFERENCE_KEY);
      if (cachedPreference === 'true' || cachedPreference === 'false') this.isCollapsedPreference = cachedPreference === 'true';
    } catch { /* Keep defaults when local storage cannot be read. */ }
  }
  readView(): NavigationLayoutView {
    const breakpoint = calculateNavigationBreakpoint(this.width);
    const isDesktop = breakpoint === 'wide-desktop' || breakpoint === 'compact-desktop';
    return {breakpoint, isDesktop,
      isCollapsed: !isDesktop || (this.isCollapsedPreference ?? breakpoint === 'compact-desktop')};
  }
  resizeViewport(width: number): NavigationLayoutView {
    this.width = width;
    return this.readView();
  }
  toggleDesktopNavigation(): NavigationLayoutView {
    const view = this.readView();
    if (!view.isDesktop) return view;
    this.isCollapsedPreference = !view.isCollapsed;
    try { this.storage?.setItem(NAVIGATION_PREFERENCE_KEY, String(this.isCollapsedPreference)); }
    catch { /* Retain the user's choice in memory for this application session. */ }
    return this.readView();
  }
}
