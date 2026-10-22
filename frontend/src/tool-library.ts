import type { RJSFSchema } from '@rjsf/utils';

export interface ToolDefinition {
  id: string; kind: 'http' | 'python' | 'mcp'; display_name: string; name: string; description: string;
  input_schema: RJSFSchema; output_schema: RJSFSchema | null; enabled: boolean;
  timeout_seconds: number; created_at: string; updated_at: string;
}
export interface HttpToolDefinition extends ToolDefinition {
  kind:'http';
  method: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE' | 'HEAD' | 'OPTIONS'; url: string;
  headers:Record<string,string>; parameters:HttpParameterMapping[];
  auth?:HttpAuthBinding[];
  openapi_source?:Record<string,unknown> | null;
}
export interface HttpAuthBinding {
  id:string; kind:'bearer' | 'api_key'; location:'headers' | 'query'; name:string; value:string;
}
export interface HttpParameterMapping {
  location:'path' | 'query' | 'headers'; input_name:string; name:string;
  style?:'simple' | 'form' | null; explode?:boolean | null;
}
export type HttpToolDraft = Omit<HttpToolDefinition, 'id' | 'created_at' | 'updated_at'>;
export type PythonToolDraft = Omit<PythonToolDefinition, 'id' | 'created_at' | 'updated_at' | 'code_path' | 'source' | 'input_schema'> & {source:string; input_schema?:RJSFSchema};
export type McpToolDraft = Omit<McpToolDefinition, 'id' | 'created_at' | 'updated_at'>;
export type ToolDraft = HttpToolDraft | PythonToolDraft | McpToolDraft;
export interface ToolNameValidation {
  valid: boolean; code: 'name_invalid' | 'name_conflict' | null; message: string | null;
}
export interface PythonToolDefinition extends ToolDefinition {kind:'python'; code_path:string; source?:string}
export interface McpToolDefinition extends ToolDefinition {kind:'mcp'; connection_id:string; remote_name:string; source_tool:Record<string,unknown>}
export type AnyToolDefinition = HttpToolDefinition | PythonToolDefinition | McpToolDefinition;
export type ToolLibraryRead = ToolRead<AnyToolDefinition[]> & {reserved_names: string[]};
export interface ToolResult {
  status: 'success' | 'error' | 'timeout' | 'cancelled'; data: unknown;
  error: {code: string; message: string} | null; duration_ms: number; details: Record<string, unknown>;
}
export interface ToolTest {
  test_id: string; tool_id: string | null; created_at: string;
  status: 'running' | ToolResult['status']; result: ToolResult | null;
}
export interface ToolRead<T> {data: T; version: string}
export interface RecentToolTest {test:ToolTest; inputs:Record<string,unknown>; definition:string}
export function toolTestStatus(status:ToolTest['status']):string {
  return {running:'测试中',success:'测试成功',error:'测试失败',timeout:'测试超时',cancelled:'测试已取消'}[status];
}
export const emptyToolDraft: HttpToolDraft = {
  kind:'http', method:'GET', display_name:'', name:'tool', description:'', url:'', enabled:true,
  timeout_seconds:30, input_schema:{type:'object',properties:{},additionalProperties:false},
  output_schema:null,
  headers:{},parameters:[],auth:[],
};
export const emptyPythonToolDraft:PythonToolDraft = {
  kind:'python',display_name:'',name:'tool',description:'',enabled:true,timeout_seconds:30,
  source:'def main(quantity: int, price: float = 2.5):\n    return {"total": quantity * price}\n',
  input_schema:{type:'object',properties:{quantity:{type:'integer'},price:{type:'number'}},required:['quantity'],additionalProperties:false},
  output_schema:null,
};
export function syncHttpMappings(schema:RJSFSchema, mappings:HttpParameterMapping[]):HttpParameterMapping[] {
  const sources=['path','query','headers'].flatMap(location => {
    const group=schema.properties?.[location];
    return group && typeof group === 'object' && !group.$ref
      ? Object.keys(group.properties ?? {}).map(input_name => ({location:location as HttpParameterMapping['location'],input_name})) : [];
  });
  const preserved=mappings.filter(mapping => {
    const group=schema.properties?.[mapping.location];
    return typeof group === 'object' && Boolean(group.$ref);
  });
  return [...preserved,...sources.map(source => mappings.find(mapping => mapping.location === source.location && mapping.input_name === source.input_name)
    ?? {...source,name:source.input_name})];
}
export function suggestToolName(displayName: string, occupiedNames: Iterable<string>): string {
  let stem = displayName.replace(/[^A-Za-z0-9_]+/g, '_').replace(/^_+|_+$/g, '').slice(0, 50) || 'tool';
  if (/^[0-9]/.test(stem)) stem = `tool_${stem}`;
  const occupied = new Set(occupiedNames);
  let name = stem;
  for (let suffix = 2; occupied.has(name); suffix++) name = `${stem}_${suffix}`;
  return name;
}
export function editTool(tool: AnyToolDefinition): ToolDraft {
  if (tool.kind === 'python') {
    const {id, created_at, updated_at, code_path, source, ...draft} = tool;
    return {...draft,source:source ?? ''};
  }
  const {id, created_at, updated_at, ...draft} = tool;
  return draft;
}
export function toolDraftFingerprint(draft:ToolDraft):string {
  const normalized=draft.kind !== 'http' ? draft : {...draft,openapi_source:draft.openapi_source ?? null,headers:draft.headers === undefined ? {} : draft.headers,
    auth:(draft.auth ?? []).map(binding => ({...binding,value:binding.value ?? ''})),
    parameters:Array.isArray(draft.parameters) ? draft.parameters.map(mapping => mapping && typeof mapping === 'object' && !Array.isArray(mapping)
      ? {...mapping,style:mapping.style ?? null,explode:mapping.explode ?? null} : mapping) : draft.parameters === undefined ? [] : draft.parameters};
  return JSON.stringify(normalized,(_key,value:unknown) => value && typeof value === 'object' && !Array.isArray(value)
    ? Object.fromEntries(Object.entries(value).sort(([a],[b]) => a.localeCompare(b))) : value);
}
export function formatToolValue(value: unknown): string {
  // JSON quotes distinguish an empty string from a missing/empty display.
  return JSON.stringify(value, null, 2);
}
