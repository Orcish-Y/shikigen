import { useCallback, useEffect, useImperativeHandle, useRef, useState, type Ref } from 'react';
import { ArrowLeft, ClockCounterClockwise, Globe, Play, SidebarSimple, FloppyDisk, Trash, ToggleLeft, ToggleRight } from '@phosphor-icons/react';
import type { RJSFSchema } from '@rjsf/utils';
import { BackendRequestError, type BackendSession } from '../../backend-client';
import type { ContentView } from '../MessageBody';
import { Button } from '../ui/button';
import { Overlay } from '../Overlay';
import { schemaValidatorFor } from './SchemaForm';
import { hasNonFiniteNumber } from './JsonEditor';
import { ToolDefinitionForm } from './ToolDefinitionForm';
import { ToolInputForm } from './ToolInputForm';
import { ToolTestResult } from './ToolTestResult';
import { ToolLibrarySidebar } from './ToolLibrarySidebar';
import { ToolSummaryCard } from './ToolSummaryCard';
import { editTool, emptyToolDraft, suggestToolName, toolDraftFingerprint, toolTestStatus, type AnyToolDefinition, type HttpToolDefinition, type RecentToolTest, type ToolDraft, type ToolTest } from '../../tool-library';

const message = (error:unknown) => error instanceof Error ? error.message : String(error);
interface Editor {tool:HttpToolDefinition | null; initial:ToolDraft; draft:ToolDraft; version:string; revision:number; inputKey:number}
export interface ToolsWorkspaceHandle {requestLeave:(action:() => void) => void}
interface PendingSave {draft:ToolDraft; toolId?:string}
function rejectedSave(failure:unknown) {
  if (!(failure instanceof BackendRequestError)) return false;
  if (failure.status === 409 || failure.status === 422) return true;
  try {
    const code = JSON.parse(failure.detail).detail?.code;
    return ['config_read','config_write','config_source','not_found','definition_invalid','read_only'].includes(code);
  } catch {return false;}
}

export function ToolsWorkspace({ session, onView, onNavigation, ref }: {
  session: BackendSession | null; onView: (view: ContentView) => void;
  onNavigation?:() => void; ref?:Ref<ToolsWorkspaceHandle>;
}) {
  const [schema, setSchema] = useState<RJSFSchema | null>(null);
  const [tools, setTools] = useState<AnyToolDefinition[] | null>(null);
  const [reservedNames, setReservedNames] = useState<string[]>([]);
  const [editor, setEditor] = useState<Editor | null>(null);
  const [dirty, setDirty] = useState(false);
  const [verified, setVerified] = useState(false);
  const [busy, setBusy] = useState<'loading' | 'saving' | 'testing' | 'deleting' | null>('loading');
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [test, setTest] = useState<ToolTest | null>(null);
  const [inputs, setInputs] = useState<Record<string, unknown>>({});
  const [pendingSave, setPendingSave] = useState<PendingSave | null>(null);
  const [savedToolAwaitingRead, setSavedToolAwaitingRead] = useState<string | null>(null);
  const [recent, setRecent] = useState<Record<string,RecentToolTest>>({});
  const [testDefinition, setTestDefinition] = useState<string | null>(null);
  const [leaveAction, setLeaveAction] = useState<(() => void) | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const leaveAfterSave = useRef(false);
  const selection = useRef(0);
  useEffect(() => {
    setSchema(null); setTools(null); setReservedNames([]); setEditor(null); setTest(null); setVerified(false); setPendingSave(null);
    setSavedToolAwaitingRead(null);
    setDirty(false);setNotice(null);setInputs({});
    setRecent({});setTestDefinition(null);setLeaveAction(null);setConfirmDelete(false);leaveAfterSave.current=false;
    if (!session) {setBusy(null); return;}
    const controller = new AbortController();
    setBusy('loading'); setError(null);
    Promise.all([session.getToolManagementSchema(controller.signal), session.listTools(controller.signal)])
      .then(([management, library]) => {setSchema(management.data); setTools(library.data); setReservedNames(library.reserved_names ?? []); setVerified(true);})
      .catch(failure => {if (!controller.signal.aborted) setError(`工具库读取失败：${message(failure)}`);})
      .finally(() => {if (!controller.signal.aborted) setBusy(null);});
    return () => {controller.abort(); selection.current++;};
  }, [session]);

  function requestLeave(action:() => void) {
    if (busy || pendingSave) {setNotice('当前操作尚未完成，请完成后再离开。');return;}
    if (dirty) {setLeaveAction(() => action);leaveAfterSave.current=false;}
    else action();
  }
  useImperativeHandle(ref, () => ({requestLeave}));
  useEffect(() => {
    if (!dirty) return;
    const warn = (event:BeforeUnloadEvent) => {event.preventDefault();event.returnValue='';};
    window.addEventListener('beforeunload',warn);
    return () => window.removeEventListener('beforeunload',warn);
  }, [dirty]);
  useEffect(() => {
    if (!editor?.tool || !test?.result || !testDefinition) return;
    setRecent(current => ({...current,[editor.tool!.id]:{test,inputs,definition:testDefinition}}));
  }, [test, editor?.tool?.id, testDefinition, inputs]);

  function finishLeave() {
    const action=leaveAction;
    setLeaveAction(null);setBusy(null);leaveAfterSave.current=false;
    action?.();
  }
  function closeEditor() {
    selection.current++;setEditor(null);setTest(null);setDirty(false);setBusy(null);setNotice(null);setTestDefinition(null);
    setSavedToolAwaitingRead(null);
  }

  useEffect(() => {
    if (!session || !test || test.status !== 'running') return;
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      session.getToolTest(test.test_id, controller.signal).then(response => {
        if (controller.signal.aborted) return;
        setTest(response.data); if (response.data.status !== 'running') setBusy(null);
      }).catch(failure => {
        if (!controller.signal.aborted) {setError(`测试状态读取失败：${message(failure)}。可重新查询。`);}
      });
    }, 300);
    return () => {window.clearTimeout(timer); controller.abort();};
  }, [session, test]);

  async function reload() {
    if (!session) return;
    const request = ++selection.current;
    setBusy('loading'); setError(null); setVerified(false);
    try {
      const result = await session.listTools();
      if (request !== selection.current) return;
      setTools(result.data);
      setReservedNames(result.reserved_names ?? []);
      if (editor?.tool && result.version !== editor.version) {
        setVerified(false);setNotice('工具库已有变化，请重新选择工具读取最新配置。');
      } else setVerified(true);
    }
    catch (failure) {if (request === selection.current) setError(`工具库读取失败：${message(failure)}`);}
    finally {if (request === selection.current) setBusy(null);}
  }
  async function open(tool:AnyToolDefinition) {
    if (!session) return;
    const request = ++selection.current;
    setBusy('loading'); setError(null); setNotice(null); setVerified(false); setTest(null);
    try {
      const saved = await session.getTool(tool.id);
      if (request !== selection.current) return;
      if (saved.data.kind !== 'http') {closeEditor();setBusy(null);setVerified(true);setNotice('此类型的专属编辑与测试将在后续 ticket 接入。');return;}
      const draft=editTool(saved.data);
      setEditor({tool:saved.data, initial:draft, draft, version:saved.version, revision:request, inputKey:request});
      const previous=recent[tool.id];
      setTest(previous?.test ?? null);setInputs(previous?.inputs ?? {});setTestDefinition(previous?.definition ?? null);
      setVerified(true); setDirty(false);
      setSavedToolAwaitingRead(null);
    } catch (failure) {if (request === selection.current) setError(`工具读取失败：${message(failure)}`);}
    finally {if (request === selection.current) setBusy(null);}
  }
  async function readSavedToolDetails(toolId:string, request:number) {
    if (!session) return;
    try {
      const saved=await session.getTool(toolId);
      if (request !== selection.current) return;
      if (saved.data.kind !== 'http') throw new Error('保存后的工具类型与编辑页不一致');
      const draft=editTool(saved.data);
      setEditor({tool:saved.data,initial:draft,draft,version:saved.version,revision:request,inputKey:editor?.inputKey ?? request});
      setTools(current => [...(current ?? []).filter(tool => tool.id !== saved.data.id),saved.data]);
      setSavedToolAwaitingRead(null);setDirty(false);setVerified(true);setError(null);setNotice('工具已保存');
      if (leaveAfterSave.current) finishLeave();
    } catch (failure) {
      if (request === selection.current) {setVerified(false);setNotice('工具已保存');setError(`工具已保存，详情读取失败：${message(failure)}。可重新读取详情，无需重复保存。`);}
    }
  }
  async function retrySavedToolRead() {
    if (!savedToolAwaitingRead || busy) return;
    const request=++selection.current;
    setBusy('loading');setError(null);
    try {await readSavedToolDetails(savedToolAwaitingRead,request);}
    finally {if (request === selection.current) setBusy(null);}
  }
  async function save(value:Record<string, unknown>) {
    if (!session || !editor || busy || pendingSave || savedToolAwaitingRead) return;
    const request = ++selection.current;
    setBusy('saving'); setError(null); setNotice(null);
    let savedToolId:string;
    try {
      savedToolId = await session.saveTool(value as ToolDraft, editor.tool ? {id:editor.tool.id,version:editor.version} : undefined);
    } catch (failure) {
      if (request !== selection.current) return;
      if (rejectedSave(failure)) setError(`保存失败：${message(failure)}`);
      else {
        setPendingSave({draft:value as ToolDraft,toolId:editor.tool?.id}); setVerified(false);
        setError(`保存结果待确认：${message(failure)}。请先核实保存结果。`);
      }
      setBusy(null);return;
    }
    if (request !== selection.current) return;
    setSavedToolAwaitingRead(savedToolId);setDirty(false);setVerified(false);setNotice('工具已保存，正在读取详情…');
    try {await readSavedToolDetails(savedToolId,request);}
    finally {if (request === selection.current) setBusy(null);}
  }
  async function verifySave() {
    if (!session || !pendingSave) return;
    const request = ++selection.current;
    setBusy('loading');
    try {
      const loaded = await session.listTools();
      if (request !== selection.current) return;
      setTools(loaded.data);
      setReservedNames(loaded.reserved_names ?? []);
      const matches = loaded.data.filter(tool => tool.kind === 'http' && (!pendingSave.toolId || tool.id === pendingSave.toolId)
        && Object.entries(pendingSave.draft).every(([key,value]) => JSON.stringify(tool[key as keyof HttpToolDefinition]) === JSON.stringify(value)));
      if (matches.length !== 1) {setError('保存结果仍待确认，未找到唯一匹配的已保存定义。请核对列表后再次查询；先前请求仍可能迟到生效。'); return;}
      const tool = matches[0];
      if (tool.kind !== 'http') return;
      const draft=editTool(tool);
      setEditor({tool,initial:draft,draft,version:loaded.version,revision:request,inputKey:editor?.inputKey ?? request});
      setPendingSave(null);setSavedToolAwaitingRead(null);setVerified(true);setDirty(false);setError(null);setNotice('已核实工具保存结果');
      if (leaveAfterSave.current) finishLeave();
    } catch (failure) {if (request === selection.current) setError(`保存核实失败：${message(failure)}`);}
    finally {if (request === selection.current) setBusy(null);}
  }
  async function runTest(value:Record<string, unknown>) {
    if (!session || !editor || !canTest) return;
    const request = ++selection.current;
    setBusy('testing'); setError(null); setNotice(null); setInputs(value);setTest(null);
    setTestDefinition(toolDraftFingerprint(editor.draft));
    try {
      const started = await session.startToolDraftTest(editor.draft, value, editor.tool?.id);
      if (request === selection.current) {setTest(started.data);if (started.data.status !== 'running') setBusy(null);}
    } catch (failure) {if (request === selection.current) {setError(`无法开始草稿测试：${message(failure)}`); setBusy(null);}}
  }
  const suggestName = useCallback((displayName: string) => suggestToolName(displayName,
    [...reservedNames, ...(tools ?? []).map(tool => tool.name)]), [reservedNames, tools]);
  const validateName = useCallback(async (name: string, signal: AbortSignal) => {
    if (!session) throw new Error('后端尚未连接');
    return (await session.validateToolName(name, editor?.tool?.id, signal)).data;
  }, [session, editor?.tool?.id]);
  function create() {
    if (!session) return;
    const request = ++selection.current;
    const draft={...structuredClone(emptyToolDraft),name:suggestName('')};
    setEditor({tool:null,initial:draft,draft,version:'',revision:request,inputKey:request});
    setDirty(false);setTest(null);setNotice(null);setError(null);
    setSavedToolAwaitingRead(null);
    setInputs({});setTestDefinition(null);
  }
  async function retryTest() {
    if (!session || !test) return;
    const request = selection.current;
    try {
      const observed = await session.getToolTest(test.test_id);
      if (request !== selection.current) return;
      setTest(observed.data);setError(null);if (observed.data.status !== 'running') setBusy(null);
    } catch (failure) {if (request === selection.current) setError(message(failure));}
  }
  async function remove() {
    if (!session || !editor?.tool || busy || pendingSave || savedToolAwaitingRead) return;
    const request=++selection.current;const id=editor.tool.id;
    setBusy('deleting');setError(null);
    try {
      await session.deleteTool(id,editor.version);
      if (request !== selection.current) return;
      setTools(current => current?.filter(tool => tool.id !== id) ?? []);
      setRecent(current => {const next={...current};delete next[id];return next;});
      setConfirmDelete(false);closeEditor();setBusy(null);setNotice('工具已删除');
    } catch (failure) {if (request === selection.current) setError(`删除失败：${message(failure)}`);}
    finally {if (request === selection.current) setBusy(null);}
  }
  let validDraft=false;
  if (schema && editor && !hasNonFiniteNumber(editor.draft)) {
    const validation=schemaValidatorFor(schema).rawValidation(schema,editor.draft);
    validDraft=!validation.validationError && !validation.errors?.length;
  }
  const canTest = Boolean(editor && validDraft && !busy && verified && !pendingSave && !savedToolAwaitingRead);
  const staleTest=Boolean(test?.result && editor && testDefinition !== toolDraftFingerprint(editor.draft));
  function editDraft(draft:ToolDraft) {
    setEditor(current => current ? {...current,draft} : current);
    setDirty(Boolean(editor && toolDraftFingerprint(draft) !== toolDraftFingerprint(editor.initial)));setNotice(null);
  }
  return <div className="tool-registry">
    <ToolLibrarySidebar tools={tools} recent={recent} selectedId={editor?.tool?.id} busy={Boolean(busy)} verified={verified}
      connected={Boolean(session)} canCreate={Boolean(session && schema && verified && !busy && !pendingSave && !savedToolAwaitingRead)}
      onCreate={() => requestLeave(create)} onOpen={tool => requestLeave(() => void open(tool))} onReload={() => void reload()}/>
    <section className="tool-detail-view" aria-label="工具详情">
      <div className="tool-detail-toolbar" role="toolbar" aria-label="工具操作">
        {onNavigation && <button className="icon-button tool-navigation-toggle" aria-label="打开主导航" onClick={onNavigation}><SidebarSimple/></button>}
        <div className="tool-breadcrumb"><button aria-label="返回工具列表" disabled={Boolean(busy) || Boolean(pendingSave)}
          onClick={() => requestLeave(closeEditor)}>工具与技能</button>{editor && <><span>/</span><span>HTTP</span></>}
          {editor && <><span>/</span><strong>{editor.tool?.display_name || '新建工具'}</strong></>}</div>
        {editor && <div className="tool-toolbar-actions"><Button size="sm" variant="outline" disabled={!canTest}
          onClick={() => document.getElementById('tool-test-panel')?.scrollIntoView({behavior:'smooth',block:'start'})}><Play size={14}/>测试运行</Button>
          <Button size="sm" variant="outline" disabled={Boolean(busy) || Boolean(pendingSave) || Boolean(savedToolAwaitingRead)}
            onClick={() => editDraft({...editor.draft,enabled:!editor.draft.enabled})}>
            {editor.draft.enabled ? <ToggleRight size={14}/> : <ToggleLeft size={14}/>}{editor.draft.enabled ? '禁用此工具' : '启用此工具'}</Button>
          <Button size="sm" type="submit" form="tool-definition" disabled={!schema || Boolean(busy) || Boolean(pendingSave) || Boolean(savedToolAwaitingRead)}><FloppyDisk size={14}/>保存工具</Button>
          {editor.tool && <Button size="sm" variant="outline" aria-label="删除工具" disabled={Boolean(busy) || Boolean(pendingSave) || Boolean(savedToolAwaitingRead)} onClick={() => {setError(null);setConfirmDelete(true);}}><Trash size={14}/></Button>}
        </div>}
      </div>
      <div className="tool-detail-body">
        <div className="tool-page-notices" aria-label="工具页面提示">
          {error && !leaveAction && !confirmDelete && <p role="alert" className="business-notice">{error}</p>}
          {notice && <p role="status">{notice}</p>}
          {pendingSave && <Button size="sm" variant="outline" disabled={Boolean(busy)} onClick={verifySave}>核实保存结果</Button>}
          {savedToolAwaitingRead && !leaveAction && <><p>已保存工具 ID：<code>{savedToolAwaitingRead}</code></p><Button size="sm" variant="outline" disabled={Boolean(busy)} onClick={retrySavedToolRead}>重新读取工具详情</Button></>}
          {busy === 'loading' && tools !== null && <p role="status">正在读取工具库…</p>}
          {!verified && tools !== null && <p>读取尚未核实，不能使用旧配置开始测试。</p>}
        </div>
        {editor ? <>
          <ToolSummaryCard tool={editor.tool} initial={editor.draft} version={editor.version} dirty={dirty}/>
          <div className="tool-editor-layout">
            {schema && <ToolDefinitionForm key={editor.revision} schema={schema} initial={{...editor.initial}} formId="tool-definition" externalSubmit
              suggestName={editor.tool ? undefined : suggestName} validateName={validateName} enabled={editor.draft.enabled}
              disabled={Boolean(busy) || Boolean(pendingSave) || Boolean(savedToolAwaitingRead)} onSave={save} onInvalid={diagnostic => setError(`保存前校验失败：${diagnostic}。请继续编辑并修正。`)} onEdited={value => {
                editDraft(value as ToolDraft);
              }}/>}
            <div className="tool-test-column">
              <section className="tool-panel" aria-label="快速测试调试" id="tool-test-panel"><header className="tool-panel-heading"><Play size={16}/><h2>快速测试调试</h2><span>{busy === 'testing' ? '测试中' : '真实 HTTP 请求'}</span></header>
                <div className="tool-panel-body">
                  <p className="tool-muted">真实测试当前草稿；消费者使用已保存定义。禁用工具也可手动测试。</p>
                  {!validDraft && <p className="tool-muted">请补齐有效配置后开始测试。</p>}
                  {staleTest && <p role="status" className="tool-muted">修改前的测试结果</p>}
                  <ToolInputForm key={editor.inputKey} draft schema={validDraft ? editor.draft.input_schema : editor.initial.input_schema} disabled={!canTest} onTest={runTest}/>
                  {busy === 'testing' && <p role="status" className="tool-muted">测试中，正在请求接口并读取完整响应…</p>}
                  {busy === 'testing' && error && test && <Button size="sm" variant="outline" onClick={retryTest}>重新查询测试</Button>}
                  {test?.result ? <ToolTestResult key={test.test_id} result={test.result} inputs={inputs} onView={onView}/>
                    : <div className="tool-result-placeholder"><span>响应结果</span><pre>{busy === 'testing' ? '正在等待接口响应…' : '执行测试后，完整响应将在这里显示。'}</pre></div>}
                </div>
              </section>
              <section className="tool-panel tool-recent-test" aria-label="最近一次测试"><header className="tool-panel-heading"><ClockCounterClockwise size={16}/><h2>最近一次测试</h2><span>本页记录</span></header>
                <div className="tool-panel-body">{test ? <dl className="tool-test-facts"><dt>状态</dt><dd>{toolTestStatus(test.status)}</dd>
                  <dt>开始时间</dt><dd><time dateTime={test.created_at}>{new Date(test.created_at).toLocaleString()}</time></dd>
                  {test.result && <><dt>耗时</dt><dd>{test.result.duration_ms.toFixed(1)} ms</dd>
                    {typeof test.result.details.status_code === 'number' && <><dt>HTTP 状态</dt><dd>{test.result.details.status_code}</dd></>}</>}
                </dl> : <p className="tool-muted">暂无测试记录。执行测试后查看真实状态和耗时。</p>}</div>
              </section>
            </div>
          </div>
        </> : <div className="tool-detail-empty"><span className="tool-summary-icon"><Globe size={28}/></span><h1>{session ? '选择工具，查看配置与测试结果' : '连接后端后管理工具'}</h1>
          <p>{session ? '从左侧工具库选择已有工具，或接入一个 HTTP 工具。' : '后端尚未连接，工具配置和测试暂不可用。'}</p><span><ArrowLeft size={14}/>工具库位于左侧</span></div>}
      </div>
    </section>
    {leaveAction && <Overlay title={savedToolAwaitingRead ? '工具已保存' : '未保存的工具修改'} onClose={() => {if (!busy) {setLeaveAction(null);leaveAfterSave.current=false;}}} fallbackFocus=".tool-toolbar-actions button">
      <div className="tool-confirmation"><p>{savedToolAwaitingRead ? '保存已成功，详情尚未读取成功。可以重新读取详情，或直接离开。' : '当前草稿尚未保存。测试不会保存工具，离开后草稿不再保留。'}</p>
        {error && <p role="alert">{error}</p>}
        {pendingSave && <Button disabled={Boolean(busy)} variant="outline" onClick={verifySave}>核实保存结果</Button>}
        {savedToolAwaitingRead && <Button disabled={Boolean(busy)} variant="outline" onClick={retrySavedToolRead}>重新读取工具详情</Button>}
        <div className="tool-actions"><Button type="submit" form="tool-definition" disabled={Boolean(busy) || Boolean(pendingSave) || Boolean(savedToolAwaitingRead)} onClick={() => {leaveAfterSave.current=true;}}>保存并离开</Button>
          {savedToolAwaitingRead ? <Button variant="outline" disabled={Boolean(busy)} onClick={finishLeave}>已保存，直接离开</Button>
            : <Button variant="outline" disabled={Boolean(busy) || Boolean(pendingSave)} onClick={() => {closeEditor();finishLeave();}}>放弃修改</Button>}
          <Button variant="outline" disabled={Boolean(busy)} onClick={() => {setLeaveAction(null);leaveAfterSave.current=false;}}>继续编辑</Button></div>
      </div>
    </Overlay>}
    {confirmDelete && editor?.tool && <Overlay title="删除工具" onClose={() => {if (!busy) setConfirmDelete(false);}} fallbackFocus="[aria-label='删除工具']">
      <div className="tool-confirmation"><p>确认删除「{editor.tool.display_name}」？删除后，未来引用此 ID 的调用将报工具不存在。没有回收站。</p>
        <code>{editor.tool.id}</code>{dirty && <p>当前未保存修改也会被放弃。</p>}{error && <p role="alert">{error}</p>}
        <div className="tool-actions"><Button disabled={Boolean(busy)} onClick={remove}>确认删除</Button><Button variant="outline" disabled={Boolean(busy)} onClick={() => setConfirmDelete(false)}>取消</Button></div>
      </div>
    </Overlay>}
  </div>;
}
