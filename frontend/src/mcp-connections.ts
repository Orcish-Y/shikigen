interface McpConnectionSettings {
  display_name:string;
  test_timeout_seconds:number; discovery_timeout_seconds:number;
}
export interface McpStdioDraft extends McpConnectionSettings {
  transport:'stdio'; command:string; args:string[]; env:Record<string,string>; cwd:string | null;
}
export interface McpStreamableHttpDraft extends McpConnectionSettings {
  transport:'streamable_http'; url:string; headers:Record<string,string>;
}
export type McpConnectionDraft = McpStdioDraft | McpStreamableHttpDraft;
export type McpTransport = McpConnectionDraft['transport'];
export type McpConnection = McpConnectionDraft & {id:string; created_at:string; updated_at:string};
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
export function emptyMcpConnection(transport:McpTransport):McpConnectionDraft {
  const common={display_name:'',test_timeout_seconds:30,discovery_timeout_seconds:30};
  return transport === 'stdio' ? {...common,transport,command:'',args:[],env:{},cwd:null}
    : {...common,transport,url:'',headers:{}};
}
export function editMcpConnection(connection:McpConnection):McpConnectionDraft {
  const {id,created_at,updated_at,...draft}=connection;
  return draft;
}
export const mcpTransportLabel=(transport:McpTransport) => transport === 'stdio' ? 'stdio' : 'Streamable HTTP';
