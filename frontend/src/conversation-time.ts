export type ConversationDateGroup = '今天' | '昨天' | '更早' | '日期待确认';
export interface ConversationTime {
  group: ConversationDateGroup;
  relative: string;
  local: string;
  utc: string | null;
  original: string;
}

function parseTimestamp(timestamp: string) {
  const fields = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d+)?(Z|[+-]\d{2}:\d{2})$/i.exec(timestamp);
  if (!fields) return NaN;
  const [, year, month, day, hour, minute, second, offset] = fields;
  const isLeapYear = +year % 4 === 0 && (+year % 100 !== 0 || +year % 400 === 0);
  const days = [31,isLeapYear ? 29 : 28,31,30,31,30,31,31,30,31,30,31];
  if (+month < 1 || +month > 12 || +day < 1 || +day > days[+month - 1]
    || +hour > 23 || +minute > 59 || +second > 59
    || offset.toUpperCase() !== 'Z' && (+offset.slice(1,3) > 23 || +offset.slice(4) > 59)) return NaN;
  return Date.parse(timestamp);
}

function calendarDate(instant: number, timeZone: string) {
  const parts = new Intl.DateTimeFormat('en-CA', {timeZone, year:'numeric', month:'2-digit', day:'2-digit'})
    .formatToParts(instant);
  const part = (kind: string) => parts.find(component => component.type === kind)!.value;
  return `${part('year')}-${part('month')}-${part('day')}`;
}

/** Display-only calculations; neither the stored timestamp nor sorting is changed. */
export function presentConversationTime(timestamp?: string | null, now = Date.now(),
  timeZone = Intl.DateTimeFormat().resolvedOptions().timeZone): ConversationTime {
  const original = timestamp ?? '';
  const instant = parseTimestamp(original);
  if (!Number.isFinite(instant)) return {group:'日期待确认', relative:'时间未知',
    local:'时间未知（未取得可解析的服务端更新时间）', utc:null, original};
  const date = calendarDate(instant, timeZone);
  const today = calendarDate(now, timeZone);
  const yesterday = new Date(`${today}T00:00:00Z`);
  yesterday.setUTCDate(yesterday.getUTCDate() - 1);
  const group = date > today ? '日期待确认' : date === today ? '今天'
    : date === yesterday.toISOString().slice(0,10) ? '昨天' : '更早';
  const elapsed = now - instant;
  const absoluteDate = new Intl.DateTimeFormat('zh-CN', {timeZone, year:'numeric', month:'2-digit', day:'2-digit'}).format(instant);
  const local = `${new Intl.DateTimeFormat('zh-CN', {timeZone, year:'numeric', month:'2-digit', day:'2-digit',
    hour:'2-digit', minute:'2-digit', second:'2-digit', hourCycle:'h23', timeZoneName:'longOffset'}).format(instant)} · ${timeZone}`;
  const relative = elapsed < 0 ? `${absoluteDate} ${new Intl.DateTimeFormat('zh-CN',
    {timeZone, hour:'2-digit', minute:'2-digit', hourCycle:'h23'}).format(instant)}`
    : elapsed < 60_000 ? '刚刚' : elapsed < 3_600_000 ? `${Math.floor(elapsed / 60_000)} 分钟前`
    : elapsed < 86_400_000 ? `${Math.floor(elapsed / 3_600_000)} 小时前`
    : elapsed < 604_800_000 ? `${Math.floor(elapsed / 86_400_000)} 天前` : absoluteDate;
  return {group, relative, local, utc:/(?:Z|[+-]00:00)$/i.test(original) ? original : new Date(instant).toISOString(), original};
}

export function nextConversationTimeRefresh(now: number) {
  return 60_000 - now % 60_000;
}
