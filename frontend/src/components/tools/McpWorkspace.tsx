import {useEffect,useImperativeHandle,useRef,useState,type Ref} from 'react';
import type {RJSFSchema} from '@rjsf/utils';
import {ArrowClockwise,GearSix,Plus,SidebarSimple,PlugsConnected,Trash} from '@phosphor-icons/react';
import type {BackendSession} from '../../backend-client';
import {isVersionConflict,saveWasRejected} from '../../tool-save-errors';
import {emptyMcpConnection,editMcpConnection,mcpTransportLabel,type McpConnection,type McpConnectionDraft,type McpTransport,type McpDiscovery,type McpObservation,type McpImportedTool} from '../../mcp-connections';
import {suggestToolName,type AnyToolDefinition} from '../../tool-library';
import {SchemaForm} from './SchemaForm';
import {Button} from '../ui/button';
import {Input} from '../ui/input';
import {Overlay} from '../Overlay';
import type {ToolsWorkspaceHandle} from './ToolsWorkspace';

interface Editor {connection:McpConnection | null;draft:McpConnectionDraft;initial:McpConnectionDraft;version:string;revision:number}
const message=(error:unknown) => error instanceof Error ? error.message : String(error);

export function McpWorkspace({session,onOpenTool,onNavigation,initialConnectionId,ref}:{
  session:BackendSession | null;onOpenTool:(id:string) => void;onNavigation?:() => void;ref?:Ref<ToolsWorkspaceHandle>;
  initialConnectionId?:string;
}) {
  const [schemas,setSchemas]=useState<Partial<Record<McpTransport,RJSFSchema>>>({});
  const [connections,setConnections]=useState<McpConnection[] | null>(null);
  const [libraryVersion,setLibraryVersion]=useState('');
  const [createMenu,setCreateMenu]=useState(false);
  const [tools,setTools]=useState<AnyToolDefinition[]>([]);
  const [reserved,setReserved]=useState<string[]>([]);
  const [editor,setEditor]=useState<Editor | null>(null);
  const [busy,setBusy]=useState<string | null>(null);
  const [error,setError]=useState<string | null>(null);
  const [notice,setNotice]=useState<string | null>(null);
  const [observation,setObservation]=useState<McpObservation | null>(null);
  const [discovery,setDiscovery]=useState<McpDiscovery | null>(null);
  const [missingNames,setMissingNames]=useState<string[]>([]);
  const [selected,setSelected]=useState<string[]>([]);
  const [names,setNames]=useState<Record<string,string>>({});
  const [imported,setImported]=useState<McpImportedTool[]>([]);
  const [pendingRead,setPendingRead]=useState<string | null>(null);
  const [unknownSave,setUnknownSave]=useState(false);
  const [unknownDelete,setUnknownDelete]=useState(false);
  const [conflicted,setConflicted]=useState(false);
  const [deleteImpact,setDeleteImpact]=useState<{version:string;tools:AnyToolDefinition[]} | null>(null);
  const [leaveAction,setLeaveAction]=useState<(() => void) | null>(null);
  const leaveAfterSave=useRef(false);
  const sequence=useRef(0);
  const openedInitial=useRef<string | undefined>(undefined);
  const dirty=Boolean(editor && !pendingRead && JSON.stringify(editor.draft) !== JSON.stringify(editor.initial));
  const locked=Boolean(busy || pendingRead || unknownSave || unknownDelete || conflicted);
  const ownedTools=tools.filter(tool => tool.kind === 'mcp' && tool.connection_id === editor?.connection?.id);
  const schema=editor ? schemas[editor.draft.transport] : undefined;
  useEffect(() => {
    if (connections && initialConnectionId && openedInitial.current !== initialConnectionId) {
      openedInitial.current=initialConnectionId;void open(initialConnectionId);
    }
  },[connections,initialConnectionId]);

  useEffect(() => {
    const controller=new AbortController();const request=++sequence.current;
    openedInitial.current=undefined;
    setEditor(null);setConnections(null);setSchemas({});setCreateMenu(false);setError(null);setNotice(null);
    setConflicted(false);setLibraryVersion('');
    setObservation(null);setDiscovery(null);setMissingNames([]);setImported([]);setPendingRead(null);setUnknownSave(false);setUnknownDelete(false);setDeleteImpact(null);setLeaveAction(null);leaveAfterSave.current=false;
    if (!session) {setBusy(null);return;}
    setBusy('读取中');
    Promise.all([session.getMcpConnectionSchema('stdio',controller.signal),session.getMcpConnectionSchema('streamable_http',controller.signal),session.listMcpConnections(controller.signal),session.listTools(controller.signal)])
      .then(([stdio,http,list,library]) => {
        if (request !== sequence.current) return;
        setSchemas({stdio:stdio.data,streamable_http:http.data});setConnections(list.data);setLibraryVersion(list.version);setTools(library.data);setReserved(library.reserved_names);
      }).catch(failure => {if (!controller.signal.aborted) setError(`连接列表读取失败：${message(failure)}`);})
      .finally(() => {if (!controller.signal.aborted) setBusy(null);});
    return () => {controller.abort();sequence.current++;};
  },[session]);
  function requestLeave(action:() => void) {
    if (busy || unknownSave || unknownDelete) {setNotice('当前操作尚未核实，请完成后再离开。');return;}
    if (dirty) setLeaveAction(() => action);else action();
  }
  useImperativeHandle(ref,() => ({requestLeave}));
  useEffect(() => {
    if (!dirty) return;
    const warn=(event:BeforeUnloadEvent) => {event.preventDefault();event.returnValue='';};
    window.addEventListener('beforeunload',warn);return () => window.removeEventListener('beforeunload',warn);
  },[dirty]);
  function clearResults() {setObservation(null);setDiscovery(null);setMissingNames([]);setSelected([]);setImported([]);}
  function finishLeave() {const action=leaveAction;setLeaveAction(null);leaveAfterSave.current=false;action?.();}
  async function readDetails(id:string,request:number) {
    if (!session) return;
    const [saved,library]=await Promise.all([session.getMcpConnection(id),session.listTools()]);
    if (sequence.current !== request) return;
    const draft=editMcpConnection(saved.data);
    setEditor({connection:saved.data,draft,initial:draft,version:saved.version,revision:request});
    setLibraryVersion(saved.version);
    setConnections(current => [...(current ?? []).filter(item => item.id !== id),saved.data]);
    setTools(library.data);setReserved(library.reserved_names);
    setPendingRead(null);setError(null);
    setConflicted(false);
  }
  async function open(id:string) {
    const request=++sequence.current;setBusy('读取中');setError(null);setNotice(null);clearResults();
    try {await readDetails(id,request);}
    catch (failure) {if (request === sequence.current) setError(`连接详情读取失败：${message(failure)}`);}
    finally {if (request === sequence.current) setBusy(null);}
  }
  function create(transport:McpTransport) {
    setConflicted(false);
    const draft=emptyMcpConnection(transport);setCreateMenu(false);
    setEditor({connection:null,draft,initial:draft,version:libraryVersion,revision:++sequence.current});
    setError(null);setNotice(null);clearResults();
  }
  async function reload(discardDraft=false) {
    if (!session) return;
    const request=++sequence.current;setBusy('读取中');setError(null);
    try {
      const [list,library]=await Promise.all([session.listMcpConnections(),session.listTools()]);
      if (request !== sequence.current) return;
      setConnections(list.data);setTools(library.data);setReserved(library.reserved_names);
      setLibraryVersion(list.version);
      if (editor && !unknownSave && !unknownDelete) {
        if (dirty && !discardDraft) {
          if(list.version !== editor.version) {setConflicted(true);setNotice('连接配置或代码已有变化，草稿已保留；请放弃草稿并重读后再修改。');}
          return;
        }
        if(editor.connection && list.data.some(item => item.id === editor.connection!.id)) {
          await readDetails(editor.connection.id,request);clearResults();setNotice(null);return;
        }
      }
      setEditor(null);setUnknownSave(false);setUnknownDelete(false);setPendingRead(null);clearResults();
      setConflicted(false);
      setNotice(unknownSave || unknownDelete ? `已重读；此前${unknownDelete ? '删除' : '保存'}结果仍不确定，请查看已保存连接。` : null);
      if (leaveAction) finishLeave();
    } catch (failure) {if (request === sequence.current) setError(`连接列表读取失败：${message(failure)}`);}
    finally {if (request === sequence.current) setBusy(null);}
  }
  async function retryRead() {
    if (!pendingRead) return;
    const request=++sequence.current;setBusy('读取中');
    try {
      await readDetails(pendingRead,request);
      if (request !== sequence.current) return;
      setNotice('连接已保存');if (leaveAfterSave.current) finishLeave();
    }
    catch (failure) {if (request === sequence.current) setError(`连接已保存，详情读取失败：${message(failure)}`);}
    finally {if (request === sequence.current) setBusy(null);}
  }
  async function save(value:Record<string,unknown>) {
    if (!session || !editor || locked) return;
    const request=++sequence.current;setBusy('保存中');setError(null);setNotice(null);
    const wasExisting=Boolean(editor.connection);
    let id:string;
    try {id=await session.saveMcpConnection(value as unknown as McpConnectionDraft,editor.connection ? {id:editor.connection.id,version:editor.version} : undefined);}
    catch (failure) {
      if (request !== sequence.current) return;
      const rejected=saveWasRejected(failure);
      if (isVersionConflict(failure)) setConflicted(true);
      if (!rejected) setUnknownSave(true);
      leaveAfterSave.current=false;setError(`${rejected ? '保存失败' : '保存结果不确定，请勿重复保存'}：${message(failure)}`);setBusy(null);return;
    }
    if (request !== sequence.current) return;
    setPendingRead(id);clearResults();setNotice(wasExisting ? '连接已保存，请重新发现核对来源结构；已入库 schema 保持不变。' : '连接已保存');
    try {await readDetails(id,request);if (request === sequence.current && leaveAfterSave.current) finishLeave();}
    catch (failure) {if (request === sequence.current) setError(`连接已保存，详情读取失败：${message(failure)}。只需重新读取，无需保存。`);}
    finally {if (request === sequence.current) setBusy(null);}
  }
  async function inspect(discover:boolean) {
    if (!session || !editor?.connection || locked || dirty) return;
    const request=++sequence.current;setBusy(discover ? '发现中' : '测试中');setError(null);setNotice(null);
    if (discover) {setDiscovery(null);setMissingNames([]);setSelected([]);setImported([]);}else setObservation(null);
    try {
      if (discover) {
        const result=(await session.discoverMcpTools(editor.connection.id)).data;
        if (request !== sequence.current) return;
        setDiscovery(result);
        if (result.status === 'success') setMissingNames(result.changes?.filter(item => item.status === 'missing').map(item => item.remote_name) ?? []);
        const occupied=[...reserved,...tools.map(tool => tool.name)];const candidates:Record<string,string>={};
        for (const source of result.tools ?? []) {
          const change=result.changes?.find(item => item.remote_name === source.name);
          candidates[source.name]=change?.local_name ?? suggestToolName(source.name,occupied);
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
        await readDetails(editor.connection.id,request);
      } catch (failure) {if (request === sequence.current) setError(`工具已入库，重新读取失败：${message(failure)}`);}
    } catch (failure) {if (request === sequence.current) {
      if(isVersionConflict(failure)) setConflicted(true);
      const rejected=saveWasRejected(failure);
      if(!rejected) setUnknownSave(true);
      setError(`${rejected ? '入库失败，所选项已保留' : '保存结果不确定，请勿重复入库；可放弃草稿并重读连接列表'}：${message(failure)}`);
    }}
    finally {if (request === sequence.current) setBusy(null);}
  }
  async function prepareDelete() {
    if (!session || !editor?.connection || locked) return;
    const request=++sequence.current;setBusy('核对删除影响');setError(null);
    try {
      const library=await session.listTools();
      if (request !== sequence.current) return;
      setTools(library.data);setReserved(library.reserved_names);
      setDeleteImpact({version:library.version,tools:library.data.filter(tool => tool.kind === 'mcp' && tool.connection_id === editor.connection!.id)});
    } catch (failure) {if (request === sequence.current) setError(`删除影响读取失败：${message(failure)}`);}
    finally {if (request === sequence.current) setBusy(null);}
  }
  async function removeConnection() {
    if (!session || !editor?.connection || !deleteImpact || locked) return;
    const id=editor.connection.id,request=++sequence.current;setBusy('删除中');setError(null);setNotice(null);
    try {await session.deleteMcpConnection(id,deleteImpact.version);}
    catch (failure) {
      if (request !== sequence.current) return;
      if (!saveWasRejected(failure)) {setUnknownDelete(true);setDeleteImpact(null);}
      if(isVersionConflict(failure)) {setConflicted(true);setDeleteImpact(null);}
      setError(`${saveWasRejected(failure) ? '删除失败，请取消后刷新核对影响' : '删除结果不确定，请重读列表核实'}：${message(failure)}`);setBusy(null);return;
    }
    if (request !== sequence.current) return;
    setDeleteImpact(null);setEditor(null);clearResults();
    setConnections(current => current?.filter(item => item.id !== id) ?? null);
    setTools(current => current.filter(tool => tool.kind !== 'mcp' || tool.connection_id !== id));
    setNotice('连接及所属工具已删除');
    try {
      const [list,library]=await Promise.all([session.listMcpConnections(),session.listTools()]);
      if (request !== sequence.current) return;
      setConnections(list.data);setTools(library.data);setReserved(library.reserved_names);
    } catch (failure) {if (request === sequence.current) setError(`连接已删除，列表读取失败：${message(failure)}`);}
    finally {if (request === sequence.current) setBusy(null);}
  }
  const canInspect=Boolean(editor?.connection && !dirty && !locked);
  const status=(value:McpObservation,prefix:string) => `${prefix}${value.status === 'success' ? '成功' : value.status === 'timeout' ? '超时' : '失败'} · ${value.duration_ms.toFixed(1)} ms`;
  return <div className="tool-registry mcp-workspace">
    <aside className="tool-library-sidebar" aria-label="MCP 连接列表">
      <header className="tool-library-heading"><div className="tool-sidebar-title"><h2>MCP 服务</h2>
        <div className="tool-create-actions">
        <Button size="xs" aria-label="接入 MCP 服务" aria-expanded={createMenu} disabled={!session || !schemas.stdio || !schemas.streamable_http || locked} onClick={() => setCreateMenu(current => !current)}><Plus/>接入服务</Button>
        {createMenu && <div className="tool-create-menu"><Button variant="ghost" aria-label="新建 stdio 连接" onClick={() => requestLeave(() => create('stdio'))}>本地 stdio 服务</Button>
          <Button variant="ghost" aria-label="新建 Streamable HTTP 连接" onClick={() => requestLeave(() => create('streamable_http'))}>远程 Streamable HTTP 服务</Button></div>}</div></div>
        <p className="tool-muted">本地与远程 · 工具库独立连接</p></header>
      <div className="tool-library-items">{connections?.length === 0 && <p className="tool-list-message">暂无 MCP 连接</p>}
        {!session && <p className="tool-list-message">连接后端后管理 MCP 服务。</p>}
        <ul className="tool-library-list">{connections?.map(connection => <li key={connection.id}><button disabled={locked} aria-current={editor?.connection?.id === connection.id ? 'true' : undefined} onClick={() => requestLeave(() => void open(connection.id))}>
          <span className="tool-list-name"><strong>{connection.display_name}</strong><span className="tool-type-tag">{mcpTransportLabel(connection.transport)}</span></span>
          <span className="tool-list-description">{connection.transport === 'stdio' ? connection.command : connection.url}</span><span className="tool-list-footer">需测试确认连接状态</span></button></li>)}</ul></div>
      <footer className="tool-library-footer"><div><span>{connections?.length ?? 0} 个连接</span><button className="icon-button" aria-label="刷新连接列表" disabled={!session || Boolean(busy) || Boolean(pendingRead) || unknownSave || unknownDelete} onClick={() => void reload()}><ArrowClockwise/></button></div></footer>
    </aside>
    <section className="tool-detail-view" aria-label="MCP 服务详情"><div className="tool-detail-toolbar" role="toolbar" aria-label="MCP 服务操作">
      {onNavigation && <button className="icon-button tool-navigation-toggle" aria-label="打开主导航" onClick={onNavigation}><SidebarSimple/></button>}
      <div className="tool-breadcrumb"><span>MCP 服务</span>{editor && <><span>/</span><strong>{editor.draft.display_name || '新建连接'}</strong></>}</div>
      {editor && <div className="tool-toolbar-actions"><Button size="sm" variant="outline" disabled={!canInspect} onClick={() => void inspect(false)}>测试连接</Button>
        <Button size="sm" variant="outline" disabled={!canInspect} onClick={() => void inspect(true)}>发现工具</Button>
        <Button size="sm" type="submit" form="mcp-connection" disabled={locked}>保存连接</Button>
        {editor.connection && <Button size="sm" variant="outline" aria-label="删除连接" disabled={locked} onClick={prepareDelete}><Trash size={14}/></Button>}</div>}</div>
      <div className="tool-detail-body"><div className="tool-page-notices">
        {error && !leaveAction && !deleteImpact && <p role="alert" className="business-notice">{error}</p>}{notice && <p role="status">{notice}</p>}{busy && <p role="status">{busy}…</p>}
        {pendingRead && !leaveAction && <Button disabled={Boolean(busy)} onClick={retryRead}>重新读取连接详情</Button>}
        {conflicted && <Button disabled={Boolean(busy)} onClick={() => void reload(true)}>{editor?.connection ? '放弃草稿并重读连接详情' : '放弃草稿并重读连接列表'}</Button>}
        {unknownSave && !leaveAction && <Button disabled={Boolean(busy)} onClick={() => void reload()}>放弃草稿并重读连接列表</Button>}</div>
        {unknownDelete && <Button disabled={Boolean(busy)} onClick={() => void reload()}>重新读取连接列表核实删除</Button>}
        {editor && schema ? <><section className="tool-summary-card" aria-label="MCP 连接概览"><span className="tool-summary-icon"><PlugsConnected size={25}/></span>
          <div className="tool-summary-information"><div className="tool-summary-title"><h1>{editor.draft.display_name || `创建 ${mcpTransportLabel(editor.draft.transport)} 连接`}</h1><span className="tool-meta-tag">{mcpTransportLabel(editor.draft.transport)}</span>{dirty && <span className="tool-meta-tag unsaved">未保存修改</span>}</div>
            <p>保存连接后分别测试初始化和发现工具；勾选入库后，在工具页面调用。每次操作使用独立会话。</p>
            {editor.connection && <div className="tool-summary-id">连接 ID <code>{editor.connection.id}</code></div>}</div></section>
          <div className="tool-editor-layout"><section className="tool-panel"><header className="tool-panel-heading"><GearSix/><h2>{mcpTransportLabel(editor.draft.transport)} 连接配置</h2></header><div className="tool-panel-body">
            <SchemaForm key={editor.revision} id="mcp-connection" idPrefix="mcp-config" schema={schema} formData={editor.draft as unknown as Record<string,unknown>} disabled={locked}
              uiSchema={{'ui:submitButtonOptions':{norender:true},
                'ui:order':['display_name','transport',...(editor.draft.transport === 'stdio' ? ['command','args','env','cwd'] : ['url','headers']),'test_timeout_seconds','discovery_timeout_seconds'],
                transport:{'ui:widget':'hidden'},args:{'ui:field':'JsonSchema'},
                cwd:{'ui:help':'相对路径以配置文件所在目录为基准；留空时不指定。'},env: {'ui:field':'JsonSchema','ui:help':'以 JSON 对象填写环境变量；按原值传给本地服务。'},
                url:{'ui:help':'填写完整的 HTTP(S) MCP 端点；格式合法但暂时离线也可以保存。'},
                headers:{'ui:field':'JsonSchema','ui:help':'以 JSON 对象直接填写请求头（含认证）；保存后会原值回填。请求头不属于工具业务参数。'}}}
              onChange={event => {setEditor(current => current ? {...current,draft:event.formData as unknown as McpConnectionDraft} : current);setDiscovery(null);setSelected([]);setNotice(null);}}
              onError={errors => setError(errors.map(item => item.stack).join('；'))} onSubmit={event => void save(event.formData ?? {})}/>
            {dirty && <p className="tool-muted">请保存当前配置后再测试连接或发现工具。</p>}</div></section>
            <div className="tool-test-column"><section className="tool-panel" aria-label="连接与发现状态"><header className="tool-panel-heading"><h2>连接与发现状态</h2><span>本页观察</span></header><div className="tool-panel-body">
              {!observation && !discovery && <p className="tool-muted">尚无观察结果。连接保存成功不表示服务在线。</p>}
              {observation && <p role="status">{status(observation,'连接测试')}{dirty && '（修改前）'}</p>}
              {observation?.error && <p role="alert">{observation.error.code}：{observation.error.message}</p>}
              {discovery && <p role="status">{status(discovery,'工具发现')}</p>}{discovery?.error && <p role="alert">{discovery.error.code}：{discovery.error.message}</p>}
              {observation?.server && <details><summary>初始化事实</summary><pre className="mcp-source-json">{JSON.stringify(observation.server,null,2)}</pre></details>}</div></section>
              {discovery?.status === 'success' && <section className="tool-panel" aria-label="发现工具预览"><header className="tool-panel-heading"><h2>发现工具预览</h2><span>{discovery.tools?.length ?? 0} 项</span></header><div className="tool-panel-body mcp-discovery-list">
                <p className="tool-muted">只应用勾选项；来源更新保留 ID 和本地编辑。本次未发现的工具继续保留，不自动删除或禁用。</p>
                {discovery.tools?.map(source => {
                  const change=discovery.changes?.find(item => item.remote_name === source.name);
                  const existing=Boolean(change?.tool_id);
                  const unchanged=change?.status === 'unchanged';
                  return <div className="mcp-discovery-item" key={source.name}><label><input type="checkbox" aria-label={`选择 ${source.name}`} checked={selected.includes(source.name)} disabled={locked || unchanged} onChange={event => setSelected(current => event.target.checked ? [...current,source.name] : current.filter(name => name !== source.name))}/> <code>{source.name}</code><span className="tool-meta-tag">{unchanged ? '来源未变化' : existing ? '来源变化' : '新增'}</span></label>
                    <p>{source.description}</p><label>本地调用名称<Input aria-label={`${source.name} 本地调用名称`} value={names[source.name] ?? ''} disabled={locked || Boolean(existing)} onChange={event => setNames(current => ({...current,[source.name]:event.target.value}))}/></label>
                    {change?.status === 'changed' && <details><summary>已保存的来源结构</summary><pre className="mcp-source-json">{JSON.stringify(change.previous_source_tool,null,2)}</pre></details>}
                    <details><summary>本次来源结构与附加信息</summary><pre className="mcp-source-json">{JSON.stringify(source,null,2)}</pre></details></div>;
                })}
                {discovery.changes?.filter(item => item.status === 'missing').map(item => <div className="mcp-discovery-item" key={item.remote_name}><code>{item.remote_name}</code> <span className="tool-meta-tag">本次未发现</span><p>保留已保存定义与启用状态，实际调用以远端当次结果为准。</p></div>)}
                {!discovery.tools?.length && <p>该服务未提供工具。</p>}
                <Button disabled={!selected.length || locked || dirty} onClick={importTools}>{discovery.changes?.some(item => item.status === 'changed') ? '应用所选变更' : '导入所选工具'}</Button></div></section>}
              {imported.length > 0 && <section className="tool-panel" aria-label="入库结果"><header className="tool-panel-heading"><h2>入库结果</h2></header><div className="tool-panel-body mcp-discovery-list">{imported.map(tool => <div key={tool.id}><code>{tool.remote_name}</code><span> · {tool.existing ? '已更新来源，保留本地配置' : '已创建'}</span><Button variant="outline" disabled={locked} aria-label={`打开工具 ${tool.remote_name}`} onClick={() => requestLeave(() => onOpenTool(tool.id))}>打开工具</Button></div>)}</div></section>}
              {editor.connection && <section className="tool-panel" aria-label="所属已入库工具"><header className="tool-panel-heading"><h2>所属已入库工具</h2><span>{ownedTools.length} 项</span></header><div className="tool-panel-body mcp-discovery-list">
                {!ownedTools.length && <p className="tool-muted">暂无已入库工具。</p>}{ownedTools.map(tool => <div key={tool.id}><strong>{tool.display_name}</strong> <code>{tool.name}</code>{tool.kind === 'mcp' && missingNames.includes(tool.remote_name) && <span className="tool-meta-tag">本次未发现</span>}<Button variant="outline" disabled={locked} aria-label={`查看工具 ${tool.display_name}`} onClick={() => requestLeave(() => onOpenTool(tool.id))}>查看工具</Button></div>)}
              </div></section>}
            </div></div></> : <div className="tool-detail-empty"><h1>接入 MCP 服务</h1><p>保存 stdio 或 Streamable HTTP 连接，发现并选择需要的工具。</p></div>}
      </div></section>
    {leaveAction && <Overlay title={pendingRead ? '连接已保存' : '未保存的连接修改'} onClose={() => {if (!busy) {setLeaveAction(null);leaveAfterSave.current=false;}}}><div className="tool-confirmation"><p>{pendingRead ? '连接已保存，详情尚未读取成功；可以重读或直接离开。' : '当前连接草稿尚未保存。离开会放弃这些修改。'}</p>
      {error && <p role="alert">{error}</p>}{pendingRead && <Button disabled={Boolean(busy)} onClick={retryRead}>重新读取连接详情</Button>}
      {unknownSave && <Button disabled={Boolean(busy)} onClick={() => void reload()}>放弃草稿并重读连接列表</Button>}
      <div className="tool-actions"><Button type="submit" form="mcp-connection" disabled={locked} onClick={() => {leaveAfterSave.current=true;}}>保存并离开</Button>
        <Button disabled={Boolean(busy) || unknownSave} onClick={finishLeave}>{pendingRead ? '已保存，直接离开' : '放弃修改并离开'}</Button><Button variant="outline" disabled={Boolean(busy)} onClick={() => {setLeaveAction(null);leaveAfterSave.current=false;}}>继续编辑</Button></div></div></Overlay>}
    {deleteImpact && editor?.connection && <Overlay title="删除 MCP 连接" onClose={() => {if (!busy) setDeleteImpact(null);}} fallbackFocus="[aria-label='删除连接']"><div className="tool-confirmation">
      <p>确认删除「{editor.connection.display_name}」及其 {deleteImpact.tools.length} 个工具？未来引用这些 ID 的调用将失败，已经开始的调用继续执行。</p>
      {dirty && <p>当前未保存的连接修改也会被放弃。</p>}<ul>{deleteImpact.tools.map(tool => <li key={tool.id}>{tool.display_name} · <code>{tool.name}</code></li>)}</ul>
      {error && <p role="alert">{error}</p>}<div className="tool-actions"><Button disabled={Boolean(busy)} onClick={removeConnection}>确认删除连接及工具</Button><Button variant="outline" disabled={Boolean(busy)} onClick={() => setDeleteImpact(null)}>取消</Button></div>
    </div></Overlay>}
  </div>;
}
