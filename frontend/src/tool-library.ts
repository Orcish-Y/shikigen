import type { RJSFSchema } from '@rjsf/utils';

export interface HttpToolDefinition {
  id: string; kind: 'http'; display_name: string; name: string; description: string;
  input_schema: RJSFSchema; output_schema: RJSFSchema | null; enabled: boolean;
  timeout_seconds: number; created_at: string; updated_at: string;
  method: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE' | 'HEAD' | 'OPTIONS'; url: string;
  headers:Record<string,string>; parameters:HttpParameterMapping[];
}
export interface HttpParameterMapping {
  location:'path' | 'query' | 'headers'; input_name:string; name:string;
  style?:'simple' | 'form' | null; explode?:boolean | null;
}
export type ToolDraft = Omit<HttpToolDefinition, 'id' | 'created_at' | 'updated_at'>;
export interface ToolNameValidation {
  valid: boolean; code: 'name_invalid' | 'name_conflict' | null; message: string | null;
}
export type ToolLibraryRead = ToolRead<HttpToolDefinition[]> & {reserved_names: string[]};
export interface ToolResult {
  status: 'success' | 'error' | 'timeout' | 'cancelled'; data: unknown;
  error: {code: string; message: string} | null; duration_ms: number; details: Record<string, unknown>;
}
export interface ToolTest {
  test_id: string; tool_id: string; created_at: string;
  status: 'running' | ToolResult['status']; result: ToolResult | null;
}
export interface ToolRead<T> {data: T; version: string}
export const emptyToolDraft: ToolDraft = {
  kind:'http', method:'GET', display_name:'', name:'tool', description:'', url:'', enabled:true,
  timeout_seconds:30, input_schema:{type:'object',properties:{},additionalProperties:false},
  output_schema:null,
  headers:{},parameters:[],
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
export function editTool(tool: HttpToolDefinition): ToolDraft {
  const {id, created_at, updated_at, ...draft} = tool;
  return draft;
}
export function formatToolValue(value: unknown): string {
  // JSON quotes distinguish an empty string from a missing/empty display.
  return JSON.stringify(value, null, 2);
}
