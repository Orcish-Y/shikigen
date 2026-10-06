import { useEffect, useState } from 'react';
import { nextConversationTimeRefresh } from './conversation-time';

/** Separate from backend polling: visible wall-clock minutes only invalidate labels. */
export function useConversationTime(isVisible: boolean) {
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    if (!isVisible) return;
    let timer: ReturnType<typeof setTimeout>;
    function refreshTime() {
      const currentTime = Date.now();
      setNow(currentTime);
      timer = setTimeout(refreshTime, nextConversationTimeRefresh(currentTime));
    }
    refreshTime();
    return () => clearTimeout(timer);
  }, [isVisible]);
  return now;
}
