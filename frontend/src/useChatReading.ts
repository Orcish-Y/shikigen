import { useLayoutEffect, useRef, useState } from 'react';
import { ChatReadingPositions, READING_POSITION_EPSILON, sameTimelineLayout, movedBeyondLayoutClamp, type ReadingView, type TimelineGeometry } from './chat-reading-position';
import type { Session } from './data/demo';

function measure(timeline:HTMLElement):TimelineGeometry {
  const top = timeline.getBoundingClientRect().top + timeline.clientTop;
  return {scrollTop:timeline.scrollTop, height:timeline.clientHeight, total:timeline.scrollHeight,
    anchors:[...timeline.querySelectorAll<HTMLElement>('[data-reading-anchor]')]
      .filter(element => element.getClientRects().length > 0)
      .map(element => ({id:element.dataset.readingAnchor!, top:element.getBoundingClientRect().top - top + timeline.scrollTop}))};
}

/** 只在主时间线解释阅读意图；区内滚动与运行状态都不能开启跟随。 */
export function useChatReading(session:Session, positions:ChatReadingPositions, factsReady:boolean,
  visible:boolean, acceptedSendId:string | null) {
  const timeline = useRef<HTMLDivElement>(null);
  const [view, setView] = useState<ReadingView>({following:true, hasNewContent:false, scrollTop:null});
  const current = useRef({session, factsReady, visible, acceptedSendId});
  current.current = {session, factsReady, visible, acceptedSendId};
  const actions = useRef<{update:() => void; remember:() => void; latest:() => void; locate:(target:HTMLElement) => void} | null>(null);

  useLayoutEffect(() => {
    const element = timeline.current;
    if (!element) return;
    const threadId = session.id;
    let lastTop = element.scrollTop;
    let layout = measure(element);
    let controlsVisible = Boolean(element.parentElement?.querySelector('.reading-controls'));
    let intentUntil = 0;
    let touchY = 0;
    let connected = true;
    function publish(next:ReadingView) {
      setView(previous => previous.following === next.following && previous.hasNewContent === next.hasNewContent ? previous : next);
    }
    function content() {
      // 外层记录字段/状态/用量不属于新增正文；同一事实重放不会制造提示。
      return new Map(current.current.session.messages.map(message => [message.id,
        [message.content ?? message.text, message.code, message.record?.content]]));
    }
    function apply(next:ReadingView) {
      // 主动最新/本次接受结束之前的上翻手势，不能把其迟到 scroll 算成新的意图。
      if (next.following) intentUntil = 0;
      // 近似相等时不写 scrollTop，避免打断浏览器尚在递送的键盘滚动。
      if (next.scrollTop !== null && Math.abs(next.scrollTop - element!.scrollTop) > READING_POSITION_EPSILON) element!.scrollTop = next.scrollTop;
      lastTop = element!.scrollTop;
      layout = measure(element!);
      publish(next);
    }
    function update() {
      if (!connected || !current.current.visible) return;
      const geometry = measure(element!);
      const nextControls = Boolean(element!.parentElement?.querySelector('.reading-controls'));
      // 上翻自己显示的操作行只缩小视口；保留这次手势及尚未递送的原生滚动。
      const controlResize = nextControls !== controlsVisible
        && sameTimelineLayout({...layout, height:geometry.height}, geometry);
      controlsVisible = nextControls;
      // React 更新也可能先于原生 scroll：先采集真实移动，再恢复新布局中的偏移。
      if (performance.now() < intentUntil && movedBeyondLayoutClamp(layout, geometry)) {
        positions.userScroll(threadId, sameTimelineLayout(layout, geometry) ? geometry : {...layout, scrollTop:geometry.scrollTop},
          geometry.scrollTop < lastTop ? 'up' : 'down');
        intentUntil = performance.now() + 1000;
      }
      if (!sameTimelineLayout(layout, geometry) && !controlResize) intentUntil = 0;
      apply(positions.reconcile(threadId, geometry, content(), current.current.factsReady, current.current.acceptedSendId));
    }
    function owner(target:EventTarget | null) {
      let node = target instanceof Element ? target : null;
      while (node && node !== element) {
        const style = getComputedStyle(node);
        if (/(auto|scroll)/.test(style.overflowY) && node.scrollHeight > node.clientHeight
          || /(auto|scroll)/.test(style.overflowX) && node.scrollWidth > node.clientWidth) return false;
        node = node.parentElement;
      }
      return node === element;
    }
    function intent(up:boolean) {
      intentUntil = performance.now() + 1000;
      if (up) {
        positions.userScroll(threadId, measure(element!), 'up');
        update();
      }
    }
    function scroll() {
      const geometry = measure(element!);
      if (current.current.visible && (!sameTimelineLayout(layout, geometry) || geometry.scrollTop !== lastTop)) update();
      lastTop = element!.scrollTop;
    }
    function wheel(event:WheelEvent) { if (owner(event.target) && event.deltaY) intent(event.deltaY < 0); }
    function key(event:KeyboardEvent) {
      if (!owner(event.target) || event.altKey || event.ctrlKey || event.metaKey
        || event.target instanceof Element && event.target.closest('input,textarea,select,[contenteditable=true]')) return;
      if (['ArrowUp','PageUp','Home'].includes(event.key) || event.key === ' ' && event.shiftKey) intent(true);
      else if (['ArrowDown','PageDown','End',' '].includes(event.key)) intent(false);
    }
    function touchStart(event:TouchEvent) { touchY = event.touches[0]?.clientY ?? 0; }
    function touchMove(event:TouchEvent) {
      const y = event.touches[0]?.clientY ?? touchY;
      if (owner(event.target) && y !== touchY) intent(y > touchY);
      touchY = y;
    }
    function pointer(event:PointerEvent) { if (event.target === element && event.button === 0) intent(false); }
    const controller = {
      update,
      remember:() => { if (current.current.visible) positions.remember(threadId, measure(element)); },
      latest:() => { if (current.current.visible) apply(positions.latest(threadId, measure(element))); },
      locate:(target:HTMLElement) => {
        if (!current.current.visible || !element.contains(target)) return;
        element.scrollTop += target.getBoundingClientRect().top - element.getBoundingClientRect().top - element.clientTop;
        positions.userScroll(threadId, measure(element), 'up');
        lastTop = element.scrollTop;
        update();
        target.focus({preventScroll:true});
      },
    };
    actions.current = controller;
    const resize = new ResizeObserver(update);
    resize.observe(element);
    const container = element.querySelector('.message-container');
    if (container) resize.observe(container);
    // 子节点增高但父布局高度不变时（例工具局部滚动区），也重新核对锚点。
    const mutation = new MutationObserver(update);
    if (container) mutation.observe(container, {childList:true, subtree:true, characterData:true, attributes:true});
    element.addEventListener('scroll', scroll, {passive:true});
    element.addEventListener('wheel', wheel, {passive:true});
    element.addEventListener('keydown', key);
    element.addEventListener('touchstart', touchStart, {passive:true});
    element.addEventListener('touchmove', touchMove, {passive:true});
    element.addEventListener('pointerdown', pointer);
    update();
    return () => {
      if (element.isConnected) controller.remember();
      connected = false;
      resize.disconnect(); mutation.disconnect();
      element.removeEventListener('scroll', scroll);
      element.removeEventListener('wheel', wheel);
      element.removeEventListener('keydown', key);
      element.removeEventListener('touchstart', touchStart);
      element.removeEventListener('touchmove', touchMove);
      element.removeEventListener('pointerdown', pointer);
      if (actions.current === controller) actions.current = null;
    };
  }, [session.id, positions]);
  useLayoutEffect(() => { actions.current?.update(); });
  return {timeline, following:view.following, hasNewContent:view.hasNewContent,
    remember:() => actions.current?.remember(), latest:() => actions.current?.latest(),
    locate:(target:HTMLElement) => actions.current?.locate(target)};
}
