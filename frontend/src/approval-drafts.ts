import { buildApprovalResponses, createApprovalDraft, createApprovalIdentity, parseApproval, type ApprovalDraft, type ApprovalResponses } from './approval-decisions.ts';
import type { ApprovalRequired } from './backend-client.ts';
import type { DraftStorage } from './message-drafts.ts';
import { validateEvent } from './run-protocol.ts';
import { sameFact } from './run-projection.ts';
import type { ObservationFailure } from './observation-recovery.ts';

export interface ApprovalSubmission {
  id:string; draftVersion:number; responses:ApprovalResponses;
  status:'pending'|'unknown'|'accepted'; retryAt:number; failure:ObservationFailure|null;
}
export interface ApprovalBackup {threadId:string; draft:ApprovalDraft; submission:ApprovalSubmission|null}
const STORAGE_KEY='shikigen.approval-drafts.v1';
const STORAGE_WARNING='本地保存不可用；审批选择和原因暂存于本次应用内，请及时复制。';
const isObject=(value:unknown):value is Record<string,unknown>=>Boolean(value)&&typeof value==='object'&&!Array.isArray(value);

/** 保存输入与身份；读取资格、连接及后端租约每次重新核实。 */
export class ApprovalDrafts {
  records:ApprovalBackup[]=[];
  storageIssue:string|null=null;
  private storage:DraftStorage|null=null;

  constructor(storage?:DraftStorage|null) {
    try {
      this.storage=storage===undefined?globalThis.localStorage??null:storage;
      if(!this.storage){this.storageIssue=STORAGE_WARNING;return;}
      const storedText=this.storage.getItem(STORAGE_KEY);
      if(!storedText)return;
      const storageSnapshot:unknown=JSON.parse(storedText);
      if(!isObject(storageSnapshot)||storageSnapshot.schema!==1||!Array.isArray(storageSnapshot.records))throw new Error('审批草稿格式无效');
      this.records=storageSnapshot.records.map(readApprovalBackup);
      if(new Set(this.records.map(record=>record.draft.identity)).size!==this.records.length)throw new Error('重复审批身份');
      if(storageSnapshot.records.some(record=>isObject(record)&&isObject(record.submission)&&record.submission.status==='pending'))this.saveRecords();
    }catch{this.storage=null;this.storageIssue=STORAGE_WARNING;}
  }

  restoreDraft(threadId:string,runId:string,request:ApprovalRequired):ApprovalDraft {
    const identity=createApprovalIdentity(runId,request);
    const record=this.records.find(record=>record.threadId===threadId&&record.draft.identity===identity);
    if(record)return record.draft;
    const draft=createApprovalDraft(runId,request);
    this.records=[...this.records,{threadId,draft,submission:null}];this.saveRecords();return draft;
  }

  saveDraft(threadId:string,draft:ApprovalDraft) {
    if(this.findRecord(threadId,draft.identity)?.draft===draft)return;
    this.records=this.records.map(record=>record.threadId===threadId&&record.draft.identity===draft.identity?{...record,draft}:record);
    this.saveRecords();
  }

  findRecord(threadId:string,identity:string) {
    return this.records.find(record=>record.threadId===threadId&&record.draft.identity===identity);
  }

  beginSubmission(threadId:string,draft:ApprovalDraft,responses:ApprovalResponses):ApprovalSubmission {
    const submission:ApprovalSubmission={id:crypto.randomUUID(),draftVersion:draft.version,responses,
      status:'pending',retryAt:0,failure:null};
    this.updateSubmission(threadId,draft.identity,submission);return submission;
  }

  markSubmissionUnknown(threadId:string,identity:string,submissionId:string,failure:ObservationFailure,retryAt=0) {
    const submission=this.findRecord(threadId,identity)?.submission;
    if(!submission||submission.id!==submissionId||submission.status==='accepted')return;
    this.updateSubmission(threadId,identity,{...submission,status:'unknown',failure,retryAt:Math.max(submission.retryAt,retryAt)});
  }

  acceptSubmission(threadId:string,identity:string,submissionId:string) {
    const submission=this.findRecord(threadId,identity)?.submission;
    if(!submission||submission.id!==submissionId||submission.status!=='pending')return;
    this.updateSubmission(threadId,identity,{...submission,status:'accepted',failure:null,retryAt:0});
  }

  private updateSubmission(threadId:string,identity:string,submission:ApprovalSubmission) {
    this.records=this.records.map(record=>record.threadId===threadId&&record.draft.identity===identity?{...record,submission}:record);
    this.saveRecords();
  }

  removeDraft(identity:string) {
    const records=this.records.filter(record=>record.draft.identity!==identity);
    if(records.length===this.records.length)return;
    this.records=records;this.saveRecords();
  }

  private saveRecords() {
    if(!this.storage)return;
    try{this.storage.setItem(STORAGE_KEY,JSON.stringify({schema:1,records:this.records}));}
    catch{this.storage=null;this.storageIssue=STORAGE_WARNING;}
  }
}

function readApprovalBackup(backupPayload:unknown):ApprovalBackup {
  if(!isObject(backupPayload)||typeof backupPayload.threadId!=='string'||!backupPayload.threadId||!isObject(backupPayload.draft))throw new Error('审批草稿身份无效');
  const draft=backupPayload.draft;
  if(typeof draft.runId!=='string'||!draft.runId||!Number.isSafeInteger(draft.version)||Number(draft.version)<0
    ||!isObject(draft.request)||!isObject(draft.choices))throw new Error('审批草稿字段无效');
  validateEvent({seq:1,created_at:'2000-01-01T00:00:00Z',category:'approval',event_type:'required',payload:draft.request},backupPayload.threadId);
  const request=draft.request as unknown as ApprovalRequired;
  if(draft.identity!==createApprovalIdentity(draft.runId,request))throw new Error('审批内容指纹无效');
  const requestModel=parseApproval(request);
  if(Object.keys(draft.choices).length!==requestModel.interrupts.length)throw new Error('审批选择身份无效');
  for(const interrupt of requestModel.interrupts){
    const choices=draft.choices[interrupt.id];
    if(!Array.isArray(choices)||choices.length!==interrupt.actions.length||!choices.every((choice,index)=>isObject(choice)
      &&typeof choice.reason==='string'&&(choice.type===null||interrupt.actions[index].allowedChoices.includes(choice.type as 'approve'|'reject'))))throw new Error('审批选择无效');
  }
  const submission=backupPayload.submission;
  if(submission!==null){
    if(!isObject(submission)||typeof submission.id!=='string'||!submission.id
      ||!Number.isSafeInteger(submission.draftVersion)||Number(submission.draftVersion)<0||Number(submission.draftVersion)>Number(draft.version)
      ||!['pending','unknown','accepted'].includes(String(submission.status))
      ||typeof submission.retryAt!=='number'||!Number.isFinite(submission.retryAt)||submission.retryAt<0
      ||!isObject(submission.responses)||!(submission.failure===null||isObject(submission.failure)
        &&typeof submission.failure.message==='string'&&typeof submission.failure.recoverable==='boolean'
        &&['http','sse','protocol','network','eof','unknown'].includes(String(submission.failure.kind))))throw new Error('审批提交记录无效');
    validateEvent({seq:2,created_at:'2000-01-01T00:00:00Z',category:'approval',event_type:'resolved',
      payload:{status:'resolved',checkpoint:request.checkpoint,responses:submission.responses}},backupPayload.threadId);
    if(submission.draftVersion===draft.version&&!sameFact(submission.responses,buildApprovalResponses(draft as unknown as ApprovalDraft)))throw new Error('提交内容与版本不一致');
  }
  return {threadId:backupPayload.threadId,draft:draft as unknown as ApprovalDraft,submission:submission===null?null:{
    ...submission as unknown as ApprovalSubmission,
    ...(submission.status==='pending'?{status:'unknown',failure:{kind:'unknown',message:'应用重开，旧审批请求的接受情况待核实；不会自动再次提交。',recoverable:false}}:{}),
  }};
}
