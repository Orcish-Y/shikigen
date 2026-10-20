export interface McpStdioDraft {
  display_name:string; transport:'stdio'; command:string; args:string[]; env:Record<string,string>; cwd:string | null;
  test_timeout_seconds:number; discovery_timeout_seconds:number;
}
export interface McpStdioConnection extends McpStdioDraft {id:string; created_at:string; updated_at:string}
export interface McpSourceTool {
  name:string; title?:string; description?:string; inputSchema:Record<string,unknown>; outputSchema?:Record<string,unknown>;
  [key:string]:unknown;
}
export interface McpObservation {
  status:'success' | 'error' | 'timeout'; connection_id:string; duration_ms:number;
  error:{code:string;message:string} | null; server?:Record<string,unknown>;
}
export interface McpDiscovery extends McpObservation {discovery_id?:string; version?:string; tools?:McpSourceTool[]}
export interface McpSelection {remote_name:string; name:string}
export interface McpImportedTool {id:string; remote_name:string; existing:boolean}
export const emptyMcpConnection:McpStdioDraft = {
  display_name:'',transport:'stdio',command:'',args:[],env:{},cwd:null,
  test_timeout_seconds:30,discovery_timeout_seconds:30,
};
export function editMcpConnection(connection:McpStdioConnection):McpStdioDraft {
  const {id,created_at,updated_at,...draft}=connection;
  return draft;
}
