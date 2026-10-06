import type { ApprovalRequired, ApprovalPayload, RunEvent } from './backend-client.ts';
import { sameFact } from './run-projection.ts';

export type ApprovalDecision = {type:'approve'} | {type:'reject'; message?:string};
export type ApprovalResponses = Record<string, {decisions:ApprovalDecision[]}>;
export interface ApprovalAction {
  name:string; args:Record<string, unknown>; description:string | null;
  allowedChoices:('approve' | 'reject')[]; allowedDecisions:string[];
}
export interface ApprovalChoice {type:'approve' | 'reject' | null; reason:string}
export interface ApprovalDraft {
  identity:string; runId:string; request:ApprovalRequired;
  choices:Record<string, ApprovalChoice[]>;
}
export interface ApprovalRecord {
  identity:string; runId:string; seq:number; request:ApprovalRequired;
  resolution:Exclude<ApprovalPayload, ApprovalRequired> | null;
}
const isObject = (value:unknown):value is Record<string, unknown> =>
  Boolean(value) && typeof value === 'object' && !Array.isArray(value);

function canonicalizeValue(value:unknown):unknown {
  if (Array.isArray(value)) return value.map(canonicalizeValue);
  if (!isObject(value)) return value;
  return Object.fromEntries(Object.keys(value).sort().map(key=>[key, canonicalizeValue(value[key])]));
}

/** 完整请求身份：键次序可变，Interrupt、动作、参数和数组次序不可变。 */
export const createApprovalIdentity = (runId:string, request:ApprovalRequired) =>
  JSON.stringify([runId, canonicalizeValue(request)]);

export function parseApproval(request:ApprovalRequired) {
  let issue:string | null = null;
  const interrupts = request.interrupts.map(interrupt => {
    const value = interrupt.value;
    const actions:ApprovalAction[] = [];
    if (!isObject(value) || !Array.isArray(value.action_requests) || !value.action_requests.length
      || !Array.isArray(value.review_configs) || value.review_configs.length !== value.action_requests.length) {
      issue = '审批动作或配置无法完整解析，本组只读。';
    } else {
      for (const [index, action] of value.action_requests.entries()) {
        const config = value.review_configs[index];
        if (!isObject(action) || typeof action.name !== 'string' || !action.name.trim() || !isObject(action.args)
          || Object.hasOwn(action, 'description') && action.description !== null && typeof action.description !== 'string'
          || !isObject(config) || config.action_name !== action.name
          || !Array.isArray(config.allowed_decisions) || !config.allowed_decisions.every(decision=>typeof decision === 'string')) {
          issue = '审批动作或配置无法完整解析，本组只读。';
          continue;
        }
        const allowedDecisions = config.allowed_decisions;
        const allowedChoices = (['approve','reject'] as const).filter(decision=>allowedDecisions.includes(decision));
        if (!allowedChoices.length) issue = '本组包含暂不支持的决策，只读查看；可以核实或取消运行。';
        actions.push({name:action.name, args:action.args, description:typeof action.description === 'string' ? action.description : null,
          allowedChoices, allowedDecisions});
      }
    }
    return {id:interrupt.id, namespace:interrupt.namespace, actions, raw:interrupt.value};
  });
  return {interrupts, issue, total:interrupts.reduce((count, interrupt)=>count+interrupt.actions.length, 0)};
}

export function createApprovalDraft(runId:string, request:ApprovalRequired):ApprovalDraft {
  return {identity:createApprovalIdentity(runId, request), runId, request,
    choices:Object.fromEntries(parseApproval(request).interrupts.map(interrupt=>[interrupt.id,
      interrupt.actions.map(()=>({type:null, reason:''}))]))};
}

export function updateApprovalChoice(draft:ApprovalDraft, interruptId:string, index:number, choiceUpdate:Partial<ApprovalChoice>):ApprovalDraft {
  const choices = draft.choices[interruptId];
  const action = parseApproval(draft.request).interrupts.find(interrupt=>interrupt.id === interruptId)?.actions[index];
  if (!choices?.[index] || !action || choiceUpdate.type && !action.allowedChoices.includes(choiceUpdate.type)) return draft;
  return {...draft, choices:{...draft.choices, [interruptId]:choices.map((choice, position)=>position === index ? {...choice, ...choiceUpdate} : choice)}};
}

export function buildApprovalResponses(draft:ApprovalDraft):ApprovalResponses | null {
  const requestModel = parseApproval(draft.request);
  if (requestModel.issue) return null;
  const responses:[string, {decisions:ApprovalDecision[]}][] = [];
  for (const interrupt of requestModel.interrupts) {
    const decisions:ApprovalDecision[] = [];
    for (const [index, action] of interrupt.actions.entries()) {
      const choice = draft.choices[interrupt.id]?.[index];
      if (!choice?.type || !action.allowedChoices.includes(choice.type)) return null;
      decisions.push(choice.type === 'approve' ? {type:'approve'}
        : choice.reason.trim() ? {type:'reject', message:choice.reason} : {type:'reject'});
    }
    responses.push([interrupt.id, {decisions}]);
  }
  return Object.fromEntries(responses);
}

/** 历史只来自真实 required / resolved / invalidated；本地选择不产生处理记录。 */
export function collectApprovalRecords(events:Record<string, RunEvent[]>):ApprovalRecord[] {
  const records:ApprovalRecord[] = [];
  for (const [runId, runEvents] of Object.entries(events)) {
    for (const event of runEvents) {
      if (event.category !== 'approval' || event.payload.status !== 'required') continue;
      const request = event.payload;
      const resolution = runEvents.find(candidate=>candidate.category === 'approval'
        && candidate.seq > event.seq && candidate.payload.status !== 'required'
        && sameFact(candidate.payload.checkpoint, request.checkpoint));
      records.push({identity:createApprovalIdentity(runId, request), runId, seq:event.seq, request,
        resolution:resolution?.category === 'approval' && resolution.payload.status !== 'required' ? resolution.payload : null});
    }
  }
  return records.sort((left, right)=>left.seq-right.seq);
}
