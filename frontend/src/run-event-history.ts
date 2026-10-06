import type { BackendSession, RunEvent } from './backend-client.ts';
import { ObservationRecovery, type ObservationFailure, type RecoveryUpdate } from './observation-recovery.ts';

export interface EventRead {
  phase:'idle' | 'reading' | 'ready' | 'error';
  isLoaded:boolean;
  failure:ObservationFailure | null;
  retry:RecoveryUpdate['retry'];
}
export const emptyEventRead:EventRead={phase:'idle',isLoaded:false,failure:null,retry:null};
export interface EventTarget {session:BackendSession; threadId:string; runId:string}

/** One details-only read owner. Boundary notifications coalesce into one serial supplement. */
export class RunEventHistoryReader {
  private target:EventTarget | null=null;
  private request:{controller:AbortController; task:Promise<void>} | null=null;
  private boundaryRevision=0;
  private boundaryKeys=new Set<string>();
  private retryDeadlines=new Map<string,number>();
  private loadedTargets=new Set<string>();
  constructor(
    private mergeEvents:(target:EventTarget,events:RunEvent[])=>void,
    private publishRead:(target:EventTarget,eventRead:EventRead)=>void,
  ) {}

  private createTargetKey(target:EventTarget) {
    return JSON.stringify([target.session.startupId,target.session.baseUrl,target.threadId,target.runId]);
  }
  setTarget(target:EventTarget | null) {
    if (target?.session===this.target?.session && target?.threadId===this.target?.threadId
      && target?.runId===this.target?.runId) return;
    const previousTarget=this.target;
    this.request?.controller.abort(); this.request=null; this.target=target;
    this.boundaryKeys.clear(); this.boundaryRevision=0;
    if(previousTarget) this.publishRead(previousTarget,{...emptyEventRead,isLoaded:this.loadedTargets.has(this.createTargetKey(previousTarget))});
    if(target) void this.refreshHistory();
  }
  notifyBoundary(key:string) {
    if(!this.target || this.boundaryKeys.has(key)) return;
    this.boundaryKeys.add(key); this.boundaryRevision++;
    void this.refreshHistory();
  }
  refreshHistory():Promise<void> {
    const target=this.target;
    if(!target || target.session.signal.aborted) return Promise.resolve();
    if(this.request) return this.request.task;
    const controller=new AbortController(), request={controller,task:Promise.resolve()};
    this.request=request;
    request.task=Promise.resolve().then(async()=>{
      const isCurrent=()=>this.target===target && this.request===request && !controller.signal.aborted && !target.session.signal.aborted;
      const key=this.createTargetKey(target);
      const recovery=new ObservationRecovery(AbortSignal.any([controller.signal,target.session.signal]),
        this.retryDeadlines.get(key) ?? 0,update=>{
          if(!isCurrent()) return;
          this.retryDeadlines.set(key,Math.max(this.retryDeadlines.get(key) ?? 0,recovery.retryAt));
          this.publishRead(target,{phase:update.observation==='failed'?'error':'reading',
            isLoaded:this.loadedTargets.has(key),failure:update.observationFailure,retry:update.retry});
        });
      let readRevision=this.boundaryRevision;
      const readEventsOnce=()=>recovery.run(async()=>{
        readRevision=this.boundaryRevision;
        const events=await target.session.getRunEvents(target.threadId,target.runId,controller.signal);
        if(!isCurrent()) return true;
        this.mergeEvents(target,events);
        this.loadedTargets.add(key);
        return true;
      });
      try {
        let succeeded=await readEventsOnce();
        if(succeeded && isCurrent() && readRevision<this.boundaryRevision) succeeded=await readEventsOnce();
        if(succeeded && isCurrent()) this.publishRead(target,{phase:'ready',isLoaded:true,failure:null,retry:null});
      } finally {
        if(this.request===request) this.request=null;
      }
    });
    return request.task;
  }
}
