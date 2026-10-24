import type { AnyToolDefinition, RecentToolTest } from './tool-library';
import type { McpConnection } from './mcp-connections';

export type ExtensionCategory = 'all' | 'tools' | 'mcp' | 'skill';
export interface ToolLibrarySnapshot {
  tools: AnyToolDefinition[] | null;
  recent: Record<string, RecentToolTest>;
  selectedId?: string;
  busy: boolean;
  verified: boolean;
  canCreate: boolean;
  canReload: boolean;
  error: string | null;
}
export interface McpLibrarySnapshot {
  connections: McpConnection[] | null;
  selectedId?: string;
  busy: boolean;
  locked: boolean;
  canCreate: boolean;
  canReload: boolean;
  error: string | null;
}
