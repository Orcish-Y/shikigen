import { useState } from 'react';
import { ArrowClockwise, Globe, MagnifyingGlass, Plus } from '@phosphor-icons/react';
import { Button } from '../ui/button';
import { Input } from '../ui/input';
import type { HttpToolDefinition } from '../../tool-library';

export function ToolLibrarySidebar({tools, selectedId, busy, verified, canCreate, connected, onCreate, onOpen, onReload}: {
  tools:HttpToolDefinition[] | null; selectedId?:string; busy:boolean; verified:boolean;
  canCreate:boolean; connected:boolean; onCreate:() => void; onOpen:(tool:HttpToolDefinition) => void; onReload:() => void;
}) {
  const [query, setQuery] = useState('');
  const [filter, setFilter] = useState<'all' | 'enabled' | 'disabled'>('all');
  const counts = tools ? {all:tools.length,enabled:tools.filter(tool => tool.enabled).length,disabled:tools.filter(tool => !tool.enabled).length} : null;
  const normalized = query.trim().toLocaleLowerCase();
  const filtered = tools?.filter(tool => (filter === 'all' || tool.enabled === (filter === 'enabled'))
    && [tool.display_name,tool.name,tool.description].some(value => value.toLocaleLowerCase().includes(normalized)));
  return <aside className="tool-library-sidebar" aria-label="工具库">
    <header className="tool-library-heading">
      <div className="tool-sidebar-title"><h2>工具库</h2>
        <Button size="xs" aria-label="创建 HTTP 工具" disabled={!canCreate} onClick={onCreate}><Plus/>接入工具</Button>
      </div>
      <div className="tool-search"><MagnifyingGlass size={14}/><Input type="search" aria-label="搜索工具"
        placeholder="搜索名称、调用名称或说明…" value={query} onChange={event => setQuery(event.target.value)}/></div>
      <div className="tool-library-filters" aria-label="工具筛选">
        {([{value:'all',label:'全部'},{value:'enabled',label:'已启用'},{value:'disabled',label:'已禁用'}] as const).map(item =>
          <button key={item.value} aria-pressed={filter === item.value} onClick={() => setFilter(item.value)}>
            {item.label} {counts ? `(${counts[item.value]})` : ''}
          </button>)}
      </div>
    </header>
    <div className="tool-library-items">
      {!connected && <p className="tool-list-message">后端尚未连接，工具库不可读取。</p>}
      {connected && tools === null && <p className="tool-list-message" role="status">{busy ? '正在读取工具库…' : '工具库读取失败，请刷新重试。'}</p>}
      {tools?.length === 0 && verified && <p className="tool-list-message" role="status">工具库为空。接入第一个 HTTP 工具开始测试。</p>}
      {tools && tools.length > 0 && filtered?.length === 0 && <p className="tool-list-message">没有匹配的工具。</p>}
      {filtered && filtered.length > 0 && <ul className="tool-library-list">{filtered.map(tool => <li key={tool.id}>
        <button aria-current={selectedId === tool.id ? 'true' : undefined} disabled={busy} onClick={() => onOpen(tool)}>
          <span className="tool-list-name"><Globe size={14}/><strong>{tool.display_name}</strong><span className="tool-type-tag">HTTP</span></span>
          <code>{tool.name}</code><span className="tool-list-description">{tool.description || '暂无说明'}</span>
          <span className="tool-list-footer"><span>{tool.method} · {tool.timeout_seconds} 秒</span><span className={tool.enabled ? 'tool-enabled-text' : ''}>{tool.enabled ? '已启用' : '已禁用'}</span></span>
        </button>
      </li>)}</ul>}
    </div>
    <footer className="tool-library-footer"><div><span className="tool-library-count">{counts ? `${counts.all} 项已保存工具` : '工具库'}</span>
      <button className="icon-button" disabled={!connected || busy} aria-label="刷新工具列表" title="刷新工具列表" onClick={onReload}><ArrowClockwise size={14}/></button></div>
      <p>{verified ? 'HTTP 工具 · 手动保存与测试' : '读取尚未核实'}</p>
    </footer>
  </aside>;
}
