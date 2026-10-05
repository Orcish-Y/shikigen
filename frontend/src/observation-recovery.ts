import { BackendRequestError, type RunFrame } from './backend-client.ts';
import { RunProtocolError } from './run-protocol.ts';

export type ObservationState = 'idle' | 'connecting' | 'open' | 'retry_wait' | 'closed' | 'paused' | 'failed';
export const observationLabels:Record<ObservationState, string> = {
  idle:'观察未建立', connecting:'观察连接中', open:'观察已建立', retry_wait:'等待重连',
  closed:'观察正常结束', paused:'观察已暂停', failed:'自动恢复已停止',
};
export interface ObservationFailure {
  kind:'http' | 'sse' | 'protocol' | 'network' | 'eof' | 'unknown';
  message:string;
  status?:number; detail?:string; retryAfter?:string | null;
  code?:string; recoverable:boolean; raw?:unknown;
}
export interface RecoveryUpdate {
  observation:ObservationState;
  retry: {attempt:number; at:number} | null;
  observationFailure:ObservationFailure | null;
}

export class StreamObservationError extends Error {
  readonly data:Extract<RunFrame, {event:'error'}>['data'];
  constructor(data:Extract<RunFrame, {event:'error'}>['data']) {super(data.message); this.data = data;}
}
export class UnexpectedObservationEnd extends Error {}

export function retryAfterTime(value:string | null):number {
  if (value === null) return 0;
  const trimmed = value.trim();
  const at = /^\d+$/.test(trimmed) ? Date.now() + Number(trimmed) * 1000 : Date.parse(trimmed);
  return Number.isFinite(at) ? Math.max(0, at) : 0;
}

export function observationFailure(error:unknown):ObservationFailure {
  if (error instanceof BackendRequestError) return {kind:'http', message:error.message,
    status:error.status, detail:error.detail, retryAfter:error.retryAfter, recoverable:error.status === 503};
  if (error instanceof StreamObservationError) return {kind:'sse', ...error.data};
  if (error instanceof RunProtocolError) return {kind:'protocol', message:error.message, raw:error.raw, recoverable:false};
  if (error instanceof UnexpectedObservationEnd) return {kind:'eof', message:error.message, recoverable:true};
  if (error instanceof TypeError) return {kind:'network', message:error.message, recoverable:true};
  return {kind:'unknown', message:String(error), recoverable:false};
}

export function waitUntil(at:number, signal:AbortSignal):Promise<void> {
  return new Promise((resolve, reject) => {
    let timer:ReturnType<typeof setTimeout>;
    const cleanup = () => {clearTimeout(timer); signal.removeEventListener('abort', aborted);};
    const aborted = () => {cleanup(); reject(signal.reason);};
    const check = () => {
      if (signal.aborted) {aborted(); return;}
      const remaining = at-Date.now();
      if (remaining <= 0) {cleanup(); resolve(); return;}
      timer = setTimeout(check, Math.min(remaining, 2_147_483_647));
    };
    signal.addEventListener('abort', aborted, {once:true});
    check();
  });
}

/** 一个观察轮次：只有一个读取／等待任务；执行事实由调用者保留。 */
export class ObservationRecovery {
  private attempts = 0;
  private stableTimer:ReturnType<typeof setTimeout> | null = null;
  private establishedAt:number | null = null;
  private failure:ObservationFailure | null = null;
  retryAt:number;
  private signal:AbortSignal;
  private changed:(update:RecoveryUpdate) => void;

  constructor(signal:AbortSignal, retryAt:number, changed:(update:RecoveryUpdate) => void) {
    this.signal = signal; this.retryAt = retryAt; this.changed = changed;
  }

  established() {
    if (this.signal.aborted || this.establishedAt !== null) return;
    this.establishedAt = Date.now();
    // 长工具无输出不判失败；这里只重置健康连接的失败预算。
    this.stableTimer = setTimeout(() => {this.attempts = 0; this.stableTimer = null;}, 30000);
  }

  private disconnected() {
    if (this.establishedAt !== null && Date.now()-this.establishedAt >= 30000) this.attempts = 0;
    if (this.stableTimer !== null) clearTimeout(this.stableTimer);
    this.stableTimer = null; this.establishedAt = null;
  }

  private update(observation:ObservationState, retry:RecoveryUpdate['retry'] = null) {
    if (!this.signal.aborted) this.changed({observation, retry, observationFailure:this.failure});
  }

  async run(connect:() => Promise<boolean>, initialFailure?:unknown):Promise<boolean> {
    const abort = () => this.disconnected();
    this.signal.addEventListener('abort', abort, {once:true});
    try {
      let error = initialFailure;
      let mustRecover = initialFailure !== undefined;
      while (!this.signal.aborted) {
        if (mustRecover) {
          this.failure = observationFailure(error);
          if (this.failure.kind === 'http') this.retryAt = Math.max(this.retryAt, retryAfterTime(this.failure.retryAfter ?? null));
          if (!this.failure.recoverable || this.attempts >= 3) {this.update('failed'); return false;}
          const at = Math.max(Date.now() + [1000,2000,5000][this.attempts], this.retryAt);
          this.update('retry_wait', {attempt:this.attempts+1, at});
          await waitUntil(at, this.signal);
          if (this.signal.aborted) return false;
          this.attempts++;
        } else if (this.retryAt > Date.now()) {
          // 手动重连／重新进入也不能绕过后端给出的等待期限。
          this.update('retry_wait', {attempt:0, at:this.retryAt});
          await waitUntil(this.retryAt, this.signal);
        }
        if (this.signal.aborted) return false;
        this.update('connecting');
        if (this.signal.aborted) return false;
        try {
          const normal = await connect();
          if (this.signal.aborted) return false;
          if (!normal) throw new UnexpectedObservationEnd('观察连接意外结束，最后确认的运行仍未正常结束。');
          this.attempts = 0; this.failure = null;
          this.update('closed');
          return true;
        } catch (caught) {
          if (this.signal.aborted) return false;
          error = caught; mustRecover = true;
        } finally {this.disconnected();}
      }
    } catch (caught) {
      if (!this.signal.aborted) throw caught;
    } finally {
      this.disconnected();
      this.signal.removeEventListener('abort', abort);
    }
    return false;
  }
}
