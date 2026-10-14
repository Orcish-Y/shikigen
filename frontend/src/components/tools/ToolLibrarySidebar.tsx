import { useId, useRef, useState } from 'react';
import { ArrowClockwise, MagnifyingGlass, Plus } from '@phosphor-icons/react';
import { Button } from '../ui/button';
import { Input } from '../ui/input';
import { editTool, toolDraftFingerprint, toolTestStatus, type AnyToolDefinition, type RecentToolTest } from '../../tool-library';

const categories = [
  {value:'all',label:'全部'}, {value:'http',label:'HTTP'},
  {value:'python',label:'Python'}, {value:'mcp',label:'MCP'},
] as const;

export function ToolLibrarySidebar({tools, recent, selectedId, busy, verified, canCreate, connected, onCreate, onOpen, onReload}: {
  tools:AnyToolDefinition[] | null; recent:Record<string,RecentToolTest>; selectedId?:string; busy:boolean; verified:boolean;
  canCreate:boolean; connected:boolean; onCreate:() => void; onOpen:(tool:AnyToolDefinition) => void; onReload:() => void;
}) {
  const [query, setQuery] = useState('');
  const [hideDisabled, setHideDisabled] = useState(false);
  const [kind, setKind] = useState<typeof categories[number]['value']>('all');
  const tabs = useRef<(HTMLButtonElement | null)[]>([]);
  const id = useId();
  const normalized = query.trim().toLocaleLowerCase();
  const visibleTools = tools?.filter(tool => !hideDisabled || tool.enabled);
  const filtered = visibleTools?.filter(tool => (kind === 'all' || tool.kind === kind)
    && [tool.display_name,tool.name,tool.description].some(value => value.toLocaleLowerCase().includes(normalized)));

  return <aside className="tool-library-sidebar" aria-label="工具库">
    <header className="tool-library-heading">
      <div className="tool-sidebar-title"><h2>工具与技能</h2>
        <Button size="xs" aria-label="创建 HTTP 工具" disabled={!canCreate} onClick={onCreate}><Plus/>接入工具</Button>
      </div>
      <div className="tool-search"><MagnifyingGlass size={14}/><Input type="search" aria-label="搜索工具"
        placeholder="过滤已注册工具…" value={query} onChange={event => setQuery(event.target.value)}/></div>
      <div className="tool-library-tabs" role="tablist" aria-label="工具类型">
        {categories.map((category,index) => <button key={category.value} ref={element => {tabs.current[index]=element;}}
          id={`${id}-${category.value}`} role="tab" aria-selected={kind === category.value}
          aria-controls={`${id}-items`} tabIndex={kind === category.value ? 0 : -1}
          onClick={() => setKind(category.value)} onKeyDown={event => {
            let next:number;
            if (event.key === 'ArrowRight') next=(index+1)%categories.length;
            else if (event.key === 'ArrowLeft') next=(index+categories.length-1)%categories.length;
            else if (event.key === 'Home') next=0;
            else if (event.key === 'End') next=categories.length-1;
            else return;
            event.preventDefault();setKind(categories[next].value);tabs.current[next]?.focus();
          }}>{category.label}{visibleTools && ` (${visibleTools.filter(tool => category.value === 'all' || tool.kind === category.value).length})`}</button>)}
      </div>
      <label className="tool-disabled-filter"><span>隐藏禁用工具</span>
        <input type="checkbox" role="switch" checked={hideDisabled} onChange={event => setHideDisabled(event.target.checked)}/>
      </label>
    </header>
    <div className="tool-library-items" id={`${id}-items`} role="tabpanel" aria-labelledby={`${id}-${kind}`} tabIndex={0}>
      {!connected && <p className="tool-list-message">后端尚未连接，工具库不可读取。</p>}
      {connected && tools === null && <p className="tool-list-message" role="status">{busy ? '正在读取工具库…' : '工具库读取失败，请刷新重试。'}</p>}
      {tools?.length === 0 && verified && <p className="tool-list-message" role="status">工具库为空。接入第一个 HTTP 工具开始测试。</p>}
      {tools && tools.length > 0 && filtered?.length === 0 && <p className="tool-list-message">没有匹配的工具。{hideDisabled && '已隐藏禁用工具。'}</p>}
      {filtered && filtered.length > 0 && <ul className="tool-library-list">{filtered.map(tool => {
        const source=tool.kind === 'http' ? tool.url : tool.kind === 'python' ? tool.code_path : `${tool.server_id} / ${tool.remote_name}`;
        const description=[tool.display_name !== tool.name ? tool.display_name : '',tool.description].filter(Boolean).join(' · ') || '暂无说明';
        return <li key={tool.id}><button aria-current={selectedId === tool.id ? 'true' : undefined} disabled={busy} onClick={() => onOpen(tool)}>
          <span className="tool-list-name"><strong title={tool.name}>{tool.name}</strong><span className={`tool-status-dot ${tool.enabled ? 'enabled' : ''}`} aria-hidden="true"/>
            <span className="tool-type-tag">{tool.kind === 'http' ? tool.method : tool.kind === 'python' ? 'Python' : 'MCP'}</span></span>
          <span className="tool-list-description" title={description}>{description}</span>
          <span className="tool-list-footer"><span className="tool-list-source" title={`来源：${source}`}>{source}</span>
            <span className={tool.enabled ? 'tool-enabled-text' : ''}>{tool.enabled ? '已启用' : '已禁用'}</span></span>
          {recent[tool.id] && <span className="tool-list-test">{toolTestStatus(recent[tool.id].test.status)} · <time dateTime={recent[tool.id].test.created_at}>{new Date(recent[tool.id].test.created_at).toLocaleString()}</time><span>（本页草稿测试）</span>
            {tool.kind === 'http' && recent[tool.id].definition !== toolDraftFingerprint(editTool(tool)) && <span>修改前的测试结果</span>}</span>}
        </button></li>;
      })}</ul>}
    </div>
    <footer className="tool-library-footer"><div><span className="tool-library-count">{tools ? `${tools.filter(tool => tool.enabled).length} / ${tools.length} 项已启用` : '工具库'}</span>
      <button className="icon-button" disabled={!connected || busy} aria-label="刷新工具列表" title="刷新工具列表" onClick={onReload}><ArrowClockwise size={14}/></button></div>
      <p>{verified ? '已保存定义 · 本页测试记录' : '读取尚未核实'}</p>
    </footer>
  </aside>;
}
