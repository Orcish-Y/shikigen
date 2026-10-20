import {useEffect,useImperativeHandle,useRef,useState,type Ref} from 'react';
import type {RJSFSchema} from '@rjsf/utils';
import {ArrowClockwise,GearSix,Plus,SidebarSimple,PlugsConnected} from '@phosphor-icons/react';
import type {BackendSession} from '../../backend-client';
import {saveWasRejected} from '../../tool-save-errors';
import {emptyMcpConnection,editMcpConnection,type McpStdioConnection,type McpStdioDraft,type McpDiscovery,type McpObservation,type McpImportedTool} from '../../mcp-connections';
import {suggestToolName,type AnyToolDefinition} from '../../tool-library';
import {SchemaForm} from './SchemaForm';
import {Button} from '../ui/button';
import {Input} from '../ui/input';
import {Overlay} from '../Overlay';
import type {ToolsWorkspaceHandle} from './ToolsWorkspace';

interface Editor {connection:McpStdioConnection | null;draft:McpStdioDraft;initial:McpStdioDraft;version:string;revision:number}
const message=(error:unknown) => error instanceof Error ? error.message : String(error);

export function McpWorkspace({session,onOpenTool,onNavigation,initialConnectionId,ref}:{
  session:BackendSession | null;onOpenTool:(id:string) => void;onNavigation?:() => void;ref?:Ref<ToolsWorkspaceHandle>;
  initialConnectionId?:string;
}) {
  const [schema,setSchema]=useState<RJSFSchema | null>(null);
  const [connections,setConnections]=useState<McpStdioConnection[] | null>(null);
  const [tools,setTools]=useState<AnyToolDefinition[]>([]);
  const [reserved,setReserved]=useState<string[]>([]);
  const [editor,setEditor]=useState<Editor | null>(null);
  const [busy,setBusy]=useState<string | null>(null);
  const [error,setError]=useState<string | null>(null);
  const [notice,setNotice]=useState<string | null>(null);
  const [observation,setObservation]=useState<McpObservation | null>(null);
  const [discovery,setDiscovery]=useState<McpDiscovery | null>(null);
  const [selected,setSelected]=useState<string[]>([]);
  const [names,setNames]=useState<Record<string,string>>({});
  const [imported,setImported]=useState<McpImportedTool[]>([]);
  const [pendingRead,setPendingRead]=useState<string | null>(null);
  const [unknownSave,setUnknownSave]=useState(false);
  const [leaveAction,setLeaveAction]=useState<(() => void) | null>(null);
  const sequence=useRef(0);
  const openedInitial=useRef<string | undefined>(undefined);
  const dirty=Boolean(editor && !pendingRead && JSON.stringify(editor.draft) !== JSON.stringify(editor.initial));
  const locked=Boolean(busy || pendingRead || unknownSave);
  useEffect(() => {
    if (connections && initialConnectionId && openedInitial.current !== initialConnectionId) {
      openedInitial.current=initialConnectionId;void open(initialConnectionId);
    }
  },[connections,initialConnectionId]);

  useEffect(() => {
    const controller=new AbortController();const request=++sequence.current;
    openedInitial.current=undefined;
    setEditor(null);setConnections(null);setSchema(null);setError(null);setNotice(null);
    setObservation(null);setDiscovery(null);setImported([]);setPendingRead(null);setUnknownSave(false);setLeaveAction(null);
    if (!session) {setBusy(null);return;}
    setBusy('读取中');
    Promise.all([session.getMcpConnectionSchema(controller.signal),session.listMcpConnections(controller.signal),session.listTools(controller.signal)])
      .then(([management,list,library]) => {
        if (request !== sequence.current) return;
        setSchema(management.data);setConnections(list.data);setTools(library.data);setReserved(library.reserved_names);
      }).catch(failure => {if (!controller.signal.aborted) setError(`连接列表读取失败：${message(failure)}`);})
      .finally(() => {if (!controller.signal.aborted) setBusy(null);});
    return () => {controller.abort();sequence.current++;};
  },[session]);
  function requestLeave(action:() => void) {
    if (busy || unknownSave) {setNotice('当前操作尚未核实，请完成后再离开。');return;}
    if (dirty) setLeaveAction(() => action);else action();
  }
  useImperativeHandle(ref,() => ({requestLeave}));
  useEffect(() => {
    if (!dirty) return;
    const warn=(event:BeforeUnloadEvent) => {event.preventDefault();event.returnValue='';};
    window.addEventListener('beforeunload',warn);return () => window.removeEventListener('beforeunload',warn);
  },[dirty]);
  function clearResults() {setObservation(null);setDiscovery(null);setSelected([]);setImported([]);}
  async function readDetails(id:string,request:number) {
    if (!session) return;
    const saved=await session.getMcpConnection(id);
    if (sequence.current !== request) return;
    const draft=editMcpConnection(saved.data);
    setEditor({connection:saved.data,draft,initial:draft,version:saved.version,revision:request});
    setConnections(current => [...(current ?? []).filter(item => item.id !== id),saved.data]);
    setPendingRead(null);setError(null);
  }
  async function open(id:string) {
    const request=++sequence.current;setBusy('读取中');setError(null);setNotice(null);clearResults();
    try {await readDetails(id,request);}
    catch (failure) {if (request === sequence.current) setError(`连接详情读取失败：${message(failure)}`);}
    finally {if (request === sequence.current) setBusy(null);}
  }
  function create() {
    const draft=structuredClone(emptyMcpConnection);
    setEditor({connection:null,draft,initial:draft,version:'',revision:++sequence.current});
    setError(null);setNotice(null);clearResults();
  }
  async function reload() {
    if (!session) return;
    const request=++sequence.current;setBusy('读取中');setError(null);
    try {
      const [list,library]=await Promise.all([session.listMcpConnections(),session.listTools()]);
      if (request !== sequence.current) return;
      setConnections(list.data);setTools(library.data);setReserved(library.reserved_names);
      setEditor(null);setUnknownSave(false);setPendingRead(null);clearResults();
      setNotice(unknownSave ? '已放弃草稿并重读；此前保存结果仍不确定，请查看已保存连接。' : null);
    } catch (failure) {if (request === sequence.current) setError(`连接列表读取失败：${message(failure)}`);}
    finally {if (request === sequence.current) setBusy(null);}
  }
  async function retryRead() {
    if (!pendingRead) return;
    const request=++sequence.current;setBusy('读取中');
    try {await readDetails(pendingRead,request);setNotice('连接已保存');}
    catch (failure) {if (request === sequence.current) setError(`连接已保存，详情读取失败：${message(failure)}`);}
    finally {if (request === sequence.current) setBusy(null);}
  }
  async function save(value:Record<string,unknown>) {
    if (!session || !editor || locked) return;
    const request=++sequence.current;setBusy('保存中');setError(null);setNotice(null);
    let id:string;
    try {id=await session.saveMcpConnection(value as unknown as McpStdioDraft,editor.connection ? {id:editor.connection.id,version:editor.version} : undefined);}
    catch (failure) {
      if (request !== sequence.current) return;
      const rejected=saveWasRejected(failure);
      if (!rejected) setUnknownSave(true);
      setError(`${rejected ? '保存失败' : '保存结果不确定，请勿重复保存'}：${message(failure)}`);setBusy(null);return;
    }
    if (request !== sequence.current) return;
    setPendingRead(id);clearResults();setNotice('连接已保存');
    try {await readDetails(id,request);}
    catch (failure) {if (request === sequence.current) setError(`连接已保存，详情读取失败：${message(failure)}。只需重新读取，无需保存。`);}
    finally {if (request === sequence.current) setBusy(null);}
  }
  async function inspect(discover:boolean) {
    if (!session || !editor?.connection || locked || dirty) return;
    const request=++sequence.current;setBusy(discover ? '发现中' : '测试中');setError(null);setNotice(null);
    if (discover) {setDiscovery(null);setSelected([]);setImported([]);}else setObservation(null);
    try {
      if (discover) {
        const result=(await session.discoverMcpTools(editor.connection.id)).data;
        if (request !== sequence.current) return;
        setDiscovery(result);
        const occupied=[...reserved,...tools.map(tool => tool.name)];const candidates:Record<string,string>={};
        for (const source of result.tools ?? []) {
          const existing=tools.find(tool => tool.kind === 'mcp' && tool.connection_id === editor.connection!.id && tool.remote_name === source.name);
          candidates[source.name]=existing?.name ?? suggestToolName(source.name,occupied);
          occupied.push(candidates[source.name]);
        }
        setNames(candidates);
      } else {
        const result=await session.testMcpConnection(editor.connection.id);
        if (request === sequence.current) setObservation(result.data);
      }
    } catch (failure) {if (request === sequence.current) setError(`${discover ? '工具发现' : '连接测试'}失败：${message(failure)}`);}
    finally {if (request === sequence.current) setBusy(null);}
  }
  async function importTools() {
    if (!session || !editor?.connection || !discovery?.discovery_id || !selected.length || locked || dirty) return;
    const request=++sequence.current;setBusy('入库中');setError(null);setNotice(null);
    try {
      const result=await session.importMcpTools(editor.connection.id,discovery.discovery_id,
        selected.map(remote_name => ({remote_name,name:names[remote_name]})));
      if (request !== sequence.current) return;
      setImported(result.data);setDiscovery(null);setSelected([]);setNotice('所选工具已入库');
      setPendingRead(editor.connection.id);
      try {
        const library=await session.listTools();
        if (request !== sequence.current) return;
        setTools(library.data);setReserved(library.reserved_names);
        await readDetails(editor.connection.id,request);
      } catch (failure) {if (request === sequence.current) setError(`工具已入库，重新读取失败：${message(failure)}`);}
    } catch (failure) {if (request === sequence.current) {setDiscovery(null);setError(`入库未核实：${message(failure)}。请重新发现，已入库来源将保留原 ID。`);}}
    finally {if (request === sequence.current) setBusy(null);}
  }
  const canInspect=Boolean(editor?.connection && !dirty && !locked);
  const status=(value:McpObservation,prefix:string) => `${prefix}${value.status === 'success' ? '成功' : value.status === 'timeout' ? '超时' : '失败'} · ${value.duration_ms.toFixed(1)} ms`;
  return <div className="tool-registry mcp-workspace">
    <aside className="tool-library-sidebar" aria-label="MCP 连接列表">
      <header className="tool-library-heading"><div className="tool-sidebar-title"><h2>MCP 服务</h2>
        <Button size="xs" aria-label="新建 stdio 连接" disabled={!session || !schema || locked} onClick={() => requestLeave(create)}><Plus/>接入服务</Button></div>
        <p className="tool-muted">本地 stdio · 工具库独立连接</p></header>
      <div className="tool-library-items">{connections?.length === 0 && <p className="tool-list-message">暂无 MCP 连接</p>}
        {!session && <p className="tool-list-message">连接后端后管理 MCP 服务。</p>}
        <ul className="tool-library-list">{connections?.map(connection => <li key={connection.id}><button disabled={locked} aria-current={editor?.connection?.id === connection.id ? 'true' : undefined} onClick={() => requestLeave(() => void open(connection.id))}>
          <span className="tool-list-name"><strong>{connection.display_name}</strong><span className="tool-type-tag">stdio</span></span>
          <span className="tool-list-description">{connection.command}</span><span className="tool-list-footer">需测试确认连接状态</span></button></li>)}</ul></div>
      <footer className="tool-library-footer"><div><span>{connections?.length ?? 0} 个连接</span><button className="icon-button" aria-label="刷新连接列表" disabled={!session || Boolean(busy) || Boolean(pendingRead)} onClick={() => unknownSave ? void reload() : requestLeave(() => void reload())}><ArrowClockwise/></button></div></footer>
    </aside>
    <section className="tool-detail-view" aria-label="MCP 服务详情"><div className="tool-detail-toolbar" role="toolbar" aria-label="MCP 服务操作">
      {onNavigation && <button className="icon-button tool-navigation-toggle" aria-label="打开主导航" onClick={onNavigation}><SidebarSimple/></button>}
      <div className="tool-breadcrumb"><span>MCP 服务</span>{editor && <><span>/</span><strong>{editor.draft.display_name || '新建连接'}</strong></>}</div>
      {editor && <div className="tool-toolbar-actions"><Button size="sm" variant="outline" disabled={!canInspect} onClick={() => void inspect(false)}>测试连接</Button>
        <Button size="sm" variant="outline" disabled={!canInspect} onClick={() => void inspect(true)}>发现工具</Button>
        <Button size="sm" type="submit" form="mcp-connection" disabled={locked}>保存连接</Button></div>}</div>
      <div className="tool-detail-body"><div className="tool-page-notices">
        {error && <p role="alert" className="business-notice">{error}</p>}{notice && <p role="status">{notice}</p>}{busy && <p role="status">{busy}…</p>}
        {pendingRead && <Button disabled={Boolean(busy)} onClick={retryRead}>重新读取连接详情</Button>}
        {unknownSave && <Button disabled={Boolean(busy)} onClick={reload}>放弃草稿并重读连接列表</Button>}</div>
        {editor && schema ? <><section className="tool-summary-card" aria-label="MCP 连接概览"><span className="tool-summary-icon"><PlugsConnected size={25}/></span>
          <div className="tool-summary-information"><div className="tool-summary-title"><h1>{editor.draft.display_name || '创建 stdio 连接'}</h1>{dirty && <span className="tool-meta-tag unsaved">未保存修改</span>}</div>
            <p>保存连接后分别测试初始化和发现工具；勾选入库后，在工具页面调用。每次操作使用独立会话。</p>
            {editor.connection && <div className="tool-summary-id">连接 ID <code>{editor.connection.id}</code></div>}</div></section>
          <div className="tool-editor-layout"><section className="tool-panel"><header className="tool-panel-heading"><GearSix/><h2>stdio 连接配置</h2></header><div className="tool-panel-body">
            <SchemaForm key={editor.revision} id="mcp-connection" idPrefix="mcp-config" schema={schema} formData={editor.draft as unknown as Record<string,unknown>} disabled={locked}
              uiSchema={{'ui:submitButtonOptions':{norender:true},transport:{'ui:widget':'hidden'},args:{'ui:field':'JsonSchema'},
                cwd:{'ui:help':'相对路径以配置文件所在目录为基准；留空时不指定。'},env: {'ui:field':'JsonSchema','ui:help':'以 JSON 对象填写环境变量；按原值传给本地服务。'}}}
              onChange={event => {setEditor(current => current ? {...current,draft:event.formData as unknown as McpStdioDraft} : current);setDiscovery(null);setSelected([]);setNotice(null);}}
              onError={errors => setError(errors.map(item => item.stack).join('；'))} onSubmit={event => void save(event.formData ?? {})}/>
            {dirty && <p className="tool-muted">请保存当前配置后再测试连接或发现工具。</p>}</div></section>
            <div className="tool-test-column"><section className="tool-panel" aria-label="连接与发现状态"><header className="tool-panel-heading"><h2>连接与发现状态</h2><span>本页观察</span></header><div className="tool-panel-body">
              {!observation && !discovery && <p className="tool-muted">尚无观察结果。连接保存成功不表示服务在线。</p>}
              {observation && <p role="status">{status(observation,'连接测试')}{dirty && '（修改前）'}</p>}
              {observation?.error && <p role="alert">{observation.error.code}：{observation.error.message}</p>}
              {discovery && <p role="status">{status(discovery,'工具发现')}</p>}{discovery?.error && <p role="alert">{discovery.error.code}：{discovery.error.message}</p>}
              {observation?.server && <details><summary>初始化事实</summary><pre className="mcp-source-json">{JSON.stringify(observation.server,null,2)}</pre></details>}</div></section>
              {discovery?.status === 'success' && <section className="tool-panel" aria-label="发现工具预览"><header className="tool-panel-heading"><h2>发现工具预览</h2><span>{discovery.tools?.length ?? 0} 项</span></header><div className="tool-panel-body mcp-discovery-list">
                <p className="tool-muted">只将勾选项整批入库。已有来源保留工具 ID；来源更新由后续票据处理。</p>
                {discovery.tools?.map(source => {
                  const existing=tools.find(tool => tool.kind === 'mcp' && tool.connection_id === editor.connection?.id && tool.remote_name === source.name);
                  return <div className="mcp-discovery-item" key={source.name}><label><input type="checkbox" aria-label={`选择 ${source.name}`} checked={selected.includes(source.name)} disabled={locked} onChange={event => setSelected(current => event.target.checked ? [...current,source.name] : current.filter(name => name !== source.name))}/> <code>{source.name}</code>{existing && <span className="tool-meta-tag">已入库</span>}</label>
                    <p>{source.description}</p><label>本地调用名称<Input aria-label={`${source.name} 本地调用名称`} value={names[source.name] ?? ''} disabled={locked || Boolean(existing)} onChange={event => setNames(current => ({...current,[source.name]:event.target.value}))}/></label>
                    <details><summary>来源结构与附加信息</summary><pre className="mcp-source-json">{JSON.stringify(source,null,2)}</pre></details></div>;
                })}
                {!discovery.tools?.length && <p>该服务未提供工具。</p>}
                <Button disabled={!selected.length || locked || dirty} onClick={importTools}>导入所选工具</Button></div></section>}
              {imported.length > 0 && <section className="tool-panel" aria-label="入库结果"><header className="tool-panel-heading"><h2>入库结果</h2></header><div className="tool-panel-body mcp-discovery-list">{imported.map(tool => <div key={tool.id}><code>{tool.remote_name}</code><span> · {tool.existing ? '已存在，保留原项' : '已创建'}</span><Button variant="outline" disabled={locked} aria-label={`打开工具 ${tool.remote_name}`} onClick={() => requestLeave(() => onOpenTool(tool.id))}>打开工具</Button></div>)}</div></section>}
            </div></div></> : <div className="tool-detail-empty"><h1>接入本地 MCP 服务</h1><p>保存 stdio 连接、发现并选择需要的工具。</p></div>}
      </div></section>
    {leaveAction && <Overlay title="未保存的连接修改" onClose={() => setLeaveAction(null)}><div className="tool-confirmation"><p>当前连接草稿尚未保存。离开会放弃这些修改。</p><div className="tool-actions"><Button onClick={() => {const action=leaveAction;setLeaveAction(null);action();}}>放弃修改并离开</Button><Button variant="outline" onClick={() => setLeaveAction(null)}>继续编辑</Button></div></div></Overlay>}
  </div>;
}
