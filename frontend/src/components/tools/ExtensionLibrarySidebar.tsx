import { useId, useRef, useState } from 'react';
import { ArrowClockwise, MagnifyingGlass, Plus } from '@phosphor-icons/react';
import type { ExtensionCategory, McpLibrarySnapshot, ToolLibrarySnapshot } from '../../extension-library';
import { mcpTransportLabel, type McpTransport } from '../../mcp-connections';
import type { AnyToolDefinition } from '../../tool-library';
import { Button } from '../ui/button';
import { Input } from '../ui/input';
import { ToolLibraryRows } from './ToolLibrarySidebar';

const categories = [
  {value:'all',label:'全部'}, {value:'tools',label:'工具'},
  {value:'mcp',label:'MCP'}, {value:'skill',label:'SKILL'},
] as const;

export function ExtensionLibrarySidebar({category, onCategory, toolLibrary, mcpLibrary, connected,
  activeEditor, onCreateTool, onImportOpenApi, onCreateMcp, onOpenTool, onOpenMcp, onReload}: {
  category: ExtensionCategory; onCategory: (category: ExtensionCategory) => void;
  toolLibrary: ToolLibrarySnapshot | null; mcpLibrary: McpLibrarySnapshot | null; connected: boolean;
  activeEditor: 'tools' | 'mcp';
  onCreateTool: (kind: 'http' | 'python') => void; onImportOpenApi: () => void;
  onCreateMcp: (transport: McpTransport) => void;
  onOpenTool: (tool: AnyToolDefinition) => void; onOpenMcp: (connectionId: string) => void;
  onReload: () => void;
}) {
  const [query, setQuery] = useState('');
  const [hideDisabled, setHideDisabled] = useState(false);
  const [isCreateMenuOpen, setIsCreateMenuOpen] = useState(false);
  const tabs = useRef<(HTMLButtonElement | null)[]>([]);
  const sidebarId = useId();
  const tools = toolLibrary?.tools ?? [];
  const connections = mcpLibrary?.connections ?? [];
  const visibleTools = tools.filter(tool => !hideDisabled || tool.enabled);
  const normalizedQuery = query.trim().toLocaleLowerCase();
  const filteredTools = visibleTools.filter(tool => [tool.display_name, tool.name, tool.description]
    .some(value => value.toLocaleLowerCase().includes(normalizedQuery)));
  const filteredConnections = connections.filter(connection => [connection.display_name,
    connection.transport === 'stdio' ? connection.command : connection.url]
    .some(value => value.toLocaleLowerCase().includes(normalizedQuery)));
  const showTools = category === 'all' || category === 'tools';
  const showMcp = category === 'all' || category === 'mcp';
  const isToolsLoaded = toolLibrary?.tools != null;
  const isMcpLoaded = mcpLibrary?.connections != null;
  const categoryCounts = {all:visibleTools.length + connections.length, tools:visibleTools.length, mcp:connections.length, skill:0};
  const categoryReadiness = {all:isToolsLoaded && isMcpLoaded, tools:isToolsLoaded, mcp:isMcpLoaded, skill:true};
  const isLoading = connected && ((showTools && (!toolLibrary || toolLibrary.busy && !isToolsLoaded))
    || (showMcp && (!mcpLibrary || mcpLibrary.busy && !isMcpLoaded)));
  const hasVisibleEntries = (showTools && filteredTools.length > 0) || (showMcp && filteredConnections.length > 0);
  const hasLibraryError = Boolean(showTools && toolLibrary?.error || showMcp && mcpLibrary?.error);
  const chooseCreation = (performCreation: () => void) => {setIsCreateMenuOpen(false);performCreation();};

  return <aside className="extensions-library" aria-label="扩展库">
    <header className="tool-library-heading">
      <div className="tool-sidebar-title"><h1>扩展</h1>
        <div className="tool-create-actions">
          <Button size="xs" aria-label="新增扩展" aria-expanded={isCreateMenuOpen}
            disabled={!toolLibrary?.canCreate && !mcpLibrary?.canCreate} onClick={() => setIsCreateMenuOpen(current => !current)}><Plus/>新增扩展</Button>
          {isCreateMenuOpen && <div className="tool-create-menu">
            <Button variant="ghost" disabled={!toolLibrary?.canCreate} onClick={() => chooseCreation(() => onCreateTool('http'))}>新建 HTTP 工具</Button>
            <Button variant="ghost" disabled={!toolLibrary?.canCreate} onClick={() => chooseCreation(() => onCreateTool('python'))}>新建 Python 工具</Button>
            <Button variant="ghost" disabled={!toolLibrary?.canCreate} onClick={() => chooseCreation(onImportOpenApi)}>导入 OpenAPI 文档</Button>
            <Button variant="ghost" disabled={!mcpLibrary?.canCreate} onClick={() => chooseCreation(() => onCreateMcp('stdio'))}>本地 stdio 服务</Button>
            <Button variant="ghost" disabled={!mcpLibrary?.canCreate} onClick={() => chooseCreation(() => onCreateMcp('streamable_http'))}>远程 Streamable HTTP 服务</Button>
            <Button variant="ghost" disabled>SKILL · 暂未开放</Button>
          </div>}
        </div>
      </div>
      <div className="tool-search"><MagnifyingGlass size={14}/><Input type="search" aria-label="搜索扩展"
        placeholder="过滤已注册扩展…" value={query} onChange={event => setQuery(event.target.value)}/></div>
      <div className="tool-library-tabs" role="tablist" aria-label="扩展分类">
        {categories.map((entry,index) => <button key={entry.value} ref={element => {tabs.current[index] = element;}}
          role="tab" id={`${sidebarId}-${entry.value}`} aria-selected={category === entry.value} aria-controls={`${sidebarId}-library`}
          tabIndex={category === entry.value ? 0 : -1} onClick={() => onCategory(entry.value)} onKeyDown={event => {
            let next: number;
            if (event.key === 'ArrowRight') next = (index + 1) % categories.length;
            else if (event.key === 'ArrowLeft') next = (index + categories.length - 1) % categories.length;
            else if (event.key === 'Home') next = 0;
            else if (event.key === 'End') next = categories.length - 1;
            else return;
            event.preventDefault();tabs.current[next]?.focus();
          }}>{entry.label} ({!connected || categoryReadiness[entry.value] ? categoryCounts[entry.value] : '…'})</button>)}
      </div>
      <label className="tool-disabled-filter"><span>隐藏禁用工具</span>
        <input type="checkbox" role="switch" checked={hideDisabled} onChange={event => setHideDisabled(event.target.checked)}/>
      </label>
    </header>
    <div className="tool-library-items extensions-library-content" id={`${sidebarId}-library`} role="tabpanel"
      aria-labelledby={`${sidebarId}-${category}`} tabIndex={0} aria-busy={isLoading}>
      {category === 'skill' ? <p className="tool-list-message">SKILL 暂未开放。</p> : <>
        {!connected && <p className="tool-list-message">后端尚未连接，扩展库不可读取。</p>}
        {isLoading && <p className="tool-list-message" role="status">正在读取扩展库…</p>}
        {showTools && toolLibrary?.error && <p role="alert" className="tool-list-message">{toolLibrary.error}</p>}
        {showMcp && mcpLibrary?.error && <p role="alert" className="tool-list-message">{mcpLibrary.error}</p>}
        <ul className="tool-library-list">
        {showTools && <ToolLibraryRows tools={filteredTools} recent={toolLibrary?.recent ?? {}}
          selectedId={activeEditor === 'tools' ? toolLibrary?.selectedId : undefined} busy={toolLibrary?.busy ?? true} onOpen={onOpenTool}/>}
        {showMcp && filteredConnections.map(connection => <li key={connection.id}>
          <button disabled={mcpLibrary?.locked ?? true} aria-current={activeEditor === 'mcp' && mcpLibrary?.selectedId === connection.id ? 'true' : undefined} onClick={() => onOpenMcp(connection.id)}>
            <span className="tool-list-name"><strong>{connection.display_name}</strong><span className="tool-type-tag">MCP</span></span>
            <span className="tool-list-description">{connection.transport === 'stdio' ? connection.command : connection.url}</span>
            <span className="tool-list-footer">{mcpTransportLabel(connection.transport)} · 需测试确认状态</span>
          </button>
        </li>)}
        </ul>
        {connected && !isLoading && !hasLibraryError && !hasVisibleEntries && <p className="tool-list-message" role="status">
          {query.trim() || hideDisabled ? '没有匹配的扩展。' : '扩展库为空。点击新增扩展开始接入。'}
        </p>}
      </>}
    </div>
    <footer className="tool-library-footer"><div>
      <span className="tool-library-count" title="已注册工具的启用数量">{isToolsLoaded || !connected ? `${tools.filter(tool => tool.enabled).length} / ${tools.length} 项已启用` : '启用数量待确认'}</span>
      <button className="icon-button" aria-label="刷新扩展列表" title="刷新扩展列表" disabled={!toolLibrary?.canReload && !mcpLibrary?.canReload} onClick={onReload}><ArrowClockwise size={14}/></button>
    </div></footer>
  </aside>;
}
