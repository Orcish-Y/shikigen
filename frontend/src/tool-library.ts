import type { RJSFSchema } from '@rjsf/utils';

export interface HttpToolDefinition {
  id: string; kind: 'http'; display_name: string; name: string; description: string;
  input_schema: RJSFSchema; output_schema: RJSFSchema | null; enabled: boolean;
  timeout_seconds: number; created_at: string; updated_at: string; method: 'GET'; url: string;
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
};
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
