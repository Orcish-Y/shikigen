import type { BackendSession } from './backend-client.ts';
import type { ObservationFailure } from './observation-recovery.ts';

export interface UsageVerification {
  phase:'idle' | 'waiting' | 'reading' | 'paused';
  requests:number;
  pauseReason:'limit' | 'error' | null;
  nextAt:number | null;
  failure:ObservationFailure | null;
}
export const emptyUsageVerification:UsageVerification={phase:'idle',requests:0,pauseReason:null,nextAt:null,failure:null};
export interface UsageTarget {
  session:BackendSession; threadId:string; runId:string; executionStage:number;
  isEligible:boolean; isReading:boolean;
}
interface VerificationRound {
  requests:number; pauseReason:UsageVerification['pauseReason']; failure:ObservationFailure | null; nextAt:number;
}
export function createUsageTargetKey(target:Pick<UsageTarget,'session' | 'threadId' | 'runId' | 'executionStage'>) {
  return JSON.stringify([target.session.startupId,target.session.baseUrl,target.threadId,target.runId,target.executionStage]);
}

/** Owns one timer and a retained quota; all actual GETs use the shared snapshot reader. */
export class UsageVerificationCoordinator {
  private target:UsageTarget | null=null;
  private rounds=new Map<string,VerificationRound>();
  private timer:ReturnType<typeof setTimeout> | null=null;
  private scheduledKey:string | null=null;
  private lastVerificationJson='';

  constructor(private readSnapshot:()=>Promise<void>,private onVerificationChange:(verification:UsageVerification)=>void) {}

  private getRound(target:UsageTarget) {
    const key=createUsageTargetKey(target);
    let round=this.rounds.get(key);
    if(!round) {round={requests:0,pauseReason:null,failure:null,nextAt:Date.now()+5000};this.rounds.set(key,round);}
    return round;
  }
  private stopTimer() {
    if(this.timer!==null) clearTimeout(this.timer);
    this.timer=null;this.scheduledKey=null;
  }
  setTarget(target:UsageTarget | null) {
    const previousKey=this.target?createUsageTargetKey(this.target):null;
    const nextKey=target?createUsageTargetKey(target):null;
    if(previousKey!==nextKey || this.target?.session!==target?.session) this.stopTimer();
    this.target=target;
    this.synchronizeVerification();
  }
  private synchronizeVerification() {
    const target=this.target;
    if(!target) {this.stopTimer();this.emitVerification(emptyUsageVerification);return;}
    const round=this.getRound(target);
    if(!target.isEligible || target.isReading || round.pauseReason) this.stopTimer();
    if(target.isEligible && !target.isReading && !round.pauseReason && this.timer===null) {
      const key=createUsageTargetKey(target);
      this.scheduledKey=key;
      this.timer=setTimeout(()=>{
        this.timer=null;
        if(this.scheduledKey!==key || !this.target || createUsageTargetKey(this.target)!==key
          || !this.target.isEligible || this.target.isReading) return;
        this.scheduledKey=null;
        void this.readSnapshot();
      },Math.max(0,round.nextAt-Date.now()));
    }
    this.emitVerification({phase:target.isReading?'reading':!target.isEligible?'idle':round.pauseReason?'paused':'waiting',
      requests:round.requests,pauseReason:round.pauseReason,nextAt:target.isEligible && !round.pauseReason?round.nextAt:null,failure:round.failure});
  }
  private emitVerification(verification:UsageVerification) {
    // updateView synchronizes this owner too; identical publications must not recurse.
    const verificationJson=JSON.stringify(verification);
    if(verificationJson===this.lastVerificationJson) return;
    this.lastVerificationJson=verificationJson;this.onVerificationChange(verification);
  }
  hasBudget() {
    return !this.target?.isEligible || this.getRound(this.target).requests<12;
  }
  chargeRequest() {
    if(!this.target?.isEligible) return true;
    const round=this.getRound(this.target);
    if(round.requests>=12) {round.pauseReason='limit';this.synchronizeVerification();return false;}
    round.requests++;this.synchronizeVerification();return true;
  }
  completeRead(executionStage:number,failure:ObservationFailure | null) {
    if(!this.target) return;
    const round=this.getRound(this.target);
    round.nextAt=Date.now()+5000;
    // A manual read may span approval continuation; its old failure is not a new round's failure.
    if(this.target.executionStage===executionStage) {
      round.failure=failure;
      round.pauseReason=round.requests>=12?'limit':failure?'error':null;
    }
    this.synchronizeVerification();
  }
  continueVerification() {
    if(!this.target?.isEligible || this.target.isReading) return false;
    const round=this.getRound(this.target);
    round.requests=0;round.pauseReason=null;round.failure=null;
    this.stopTimer();return true;
  }
}
