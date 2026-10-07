import { sameFact } from './run-projection';
import type { ConversationView } from './conversation-state';

/** metadata 只核实身份；缺锚点必须等整轮消息读取结束再认定失效。 */
export function readingHistoryReady(view:Pick<ConversationView, 'history' | 'verified' | 'observation'>):boolean {
  return view.history === 'ready' && view.verified && (view.observation === 'idle' || view.observation === 'closed');
}

export interface TimelineGeometry {
  scrollTop:number;
  height:number;
  total:number;
  anchors:{id:string; top:number}[];
}

// 浏览器缩放下的矩形测量可有亚像素抖动，不将其当作阅读位置变化。
export const READING_POSITION_EPSILON = 0.5;

/** 浏览器因布局收缩而夹紧 scrollTop，不是新的用户阅读意图。 */
export function sameTimelineLayout(previous:TimelineGeometry, current:TimelineGeometry):boolean {
  return previous.height === current.height && previous.total === current.total
    && previous.anchors.length === current.anchors.length
    && previous.anchors.every((anchor, index) => anchor.id === current.anchors[index].id
      && Math.abs(anchor.top - current.anchors[index].top) <= READING_POSITION_EPSILON);
}

/** 需先有输入意图；尺寸变化造成的边界夹紧本身不代表用户移动。 */
export function movedBeyondLayoutClamp(previous:TimelineGeometry, current:TimelineGeometry):boolean {
  const clamped = Math.max(0, Math.min(previous.scrollTop, current.total - current.height));
  return previous.scrollTop !== current.scrollTop
    && (sameTimelineLayout(previous, current) || Math.abs(current.scrollTop - clamped) > 1);
}

export interface ReadingView { following:boolean; hasNewContent:boolean; scrollTop:number | null }
interface ReadingRecord {
  following:boolean;
  anchor:{id:string; offset:number} | null;
  order:string[];
  content:ReadonlyMap<string, unknown>;
  hasNewContent:boolean;
  acceptedSendId:string | null;
}

/** 本次 App 生命周期内的阅读意图；不保存到磁盘，也不拥有运行事实。 */
export class ChatReadingPositions {
  private records = new Map<string, ReadingRecord>();

  private record(threadId:string):ReadingRecord {
    let record = this.records.get(threadId);
    if (!record) {
      record = {following:true, anchor:null, order:[], content:new Map(), hasNewContent:false, acceptedSendId:null};
      this.records.set(threadId, record);
    }
    return record;
  }

  private capture(record:ReadingRecord, geometry:TimelineGeometry) {
    const anchor = [...geometry.anchors].reverse().find(item => item.top <= geometry.scrollTop)
      ?? geometry.anchors[0];
    record.anchor = anchor ? {id:anchor.id, offset:anchor.top - geometry.scrollTop} : null;
    record.order = geometry.anchors.map(item => item.id);
  }

  userScroll(threadId:string, geometry:TimelineGeometry, direction:'up' | 'down') {
    const record = this.record(threadId);
    if (direction === 'up') record.following = false;
    else if (geometry.total - geometry.height - geometry.scrollTop <= 2) {
      record.following = true;
      record.hasNewContent = false;
    }
    this.capture(record, geometry);
  }

  remember(threadId:string, geometry:TimelineGeometry) {
    if (geometry.height > 0 && geometry.anchors.length) this.capture(this.record(threadId), geometry);
  }

  followLatest(threadId:string, geometry:TimelineGeometry):ReadingView {
    const record = this.record(threadId);
    record.following = true;
    record.hasNewContent = false;
    return this.reconcile(threadId, geometry, record.content, true);
  }

  reconcile(threadId:string, geometry:TimelineGeometry, content:ReadonlyMap<string, unknown>, factsReady:boolean,
    acceptedSendId:string | null = null):ReadingView {
    const record = this.record(threadId);
    if (geometry.height <= 0) return {following:record.following, hasNewContent:record.hasNewContent, scrollTop:null};
    if (acceptedSendId && acceptedSendId !== record.acceptedSendId) {
      record.acceptedSendId = acceptedSendId;
      record.following = true;
      record.hasNewContent = false;
    }
    if (!record.following && [...content].some(([id, value]) => !record.content.has(id) || !sameFact(record.content.get(id), value))) record.hasNewContent = true;
    record.content = content;
    let target:number | null = null;
    if (record.following) target = geometry.total - geometry.height;
    else if (record.anchor) {
      const offset = record.anchor.offset;
      let anchor = geometry.anchors.find(item => item.id === record.anchor!.id);
      if (!anchor && factsReady) {
        const index = record.order.indexOf(record.anchor.id);
        // 在上次可见内容顺序中寻找最近邻；同距时先前一项。
        for (let distance = 1; !anchor && distance < record.order.length; distance++) {
          for (const id of [record.order[index - distance], record.order[index + distance]]) {
            anchor = geometry.anchors.find(item => item.id === id);
            if (anchor) break;
          }
        }
        anchor ??= geometry.anchors[0];
        if (!anchor) { record.anchor = null; record.order = []; }
      }
      if (anchor) target = anchor.top - offset;
    }
    if (target !== null) {
      target = Math.max(0, Math.min(target, geometry.total - geometry.height));
      this.capture(record, {...geometry, scrollTop:target});
    }
    return {following:record.following, hasNewContent:record.hasNewContent, scrollTop:target};
  }
}
