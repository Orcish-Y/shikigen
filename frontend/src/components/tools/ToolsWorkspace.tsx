import { useEffect, useRef, useState } from 'react';
import { ArrowLeft, ClockCounterClockwise, Globe, Play, SidebarSimple, FloppyDisk } from '@phosphor-icons/react';
import type { RJSFSchema } from '@rjsf/utils';
import { BackendRequestError, type BackendSession } from '../../backend-client';
import type { ContentView } from '../MessageBody';
import { Button } from '../ui/button';
import { ToolDefinitionForm } from './ToolDefinitionForm';
import { ToolInputForm } from './ToolInputForm';
import { ToolTestResult } from './ToolTestResult';
import { ToolLibrarySidebar } from './ToolLibrarySidebar';
import { ToolSummaryCard } from './ToolSummaryCard';
import { editTool, emptyToolDraft, type HttpToolDefinition, type ToolDraft, type ToolTest } from '../../tool-library';

const message = (error:unknown) => error instanceof Error ? error.message : String(error);
interface Editor {tool:HttpToolDefinition | null; initial:ToolDraft; version:string; revision:number}
interface PendingSave {draft:ToolDraft; toolId?:string}
function rejectedSave(failure:unknown) {
  if (!(failure instanceof BackendRequestError)) return false;
  if (failure.status === 409 || failure.status === 422) return true;
  try {
    const code = JSON.parse(failure.detail).detail?.code;
    return ['config_read','config_write','config_source','not_found','definition_invalid','read_only'].includes(code);
  } catch {return false;}
}

export function ToolsWorkspace({ session, onView, onNavigation }: {
  session: BackendSession | null; onView: (view: ContentView) => void;
  onNavigation?:() => void;
}) {
  const [schema, setSchema] = useState<RJSFSchema | null>(null);
  const [tools, setTools] = useState<HttpToolDefinition[] | null>(null);
  const [editor, setEditor] = useState<Editor | null>(null);
  const [dirty, setDirty] = useState(false);
  const [verified, setVerified] = useState(false);
  const [busy, setBusy] = useState<'loading' | 'saving' | 'testing' | null>('loading');
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [test, setTest] = useState<ToolTest | null>(null);
  const [inputs, setInputs] = useState<Record<string, unknown>>({});
  const [pendingSave, setPendingSave] = useState<PendingSave | null>(null);
  const selection = useRef(0);
  useEffect(() => {
    setSchema(null); setTools(null); setEditor(null); setTest(null); setVerified(false); setPendingSave(null);
    setDirty(false);setNotice(null);setInputs({});
    if (!session) {setBusy(null); return;}
    const controller = new AbortController();
    setBusy('loading'); setError(null);
    Promise.all([session.getToolManagementSchema(controller.signal), session.listTools(controller.signal)])
      .then(([management, library]) => {setSchema(management.data); setTools(library.data); setVerified(true);})
      .catch(failure => {if (!controller.signal.aborted) setError(`工具库读取失败：${message(failure)}`);})
      .finally(() => {if (!controller.signal.aborted) setBusy(null);});
    return () => {controller.abort(); selection.current++;};
  }, [session]);

  useEffect(() => {
    if (!session || !test || test.status !== 'running') return;
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      session.getToolTest(test.test_id, controller.signal).then(response => {
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
      if (editor?.tool && result.version !== editor.version) {
        setVerified(false);setNotice('工具库已有变化，请重新选择工具读取最新配置。');
      } else setVerified(true);
    }
    catch (failure) {if (request === selection.current) setError(`工具库读取失败：${message(failure)}`);}
    finally {if (request === selection.current) setBusy(null);}
  }
  async function open(tool:HttpToolDefinition) {
    if (!session) return;
    const request = ++selection.current;
    setBusy('loading'); setError(null); setNotice(null); setVerified(false); setTest(null);
    try {
      const saved = await session.getTool(tool.id);
      if (request !== selection.current) return;
      setEditor({tool:saved.data, initial:editTool(saved.data), version:saved.version, revision:request});
      setVerified(true); setDirty(false);
    } catch (failure) {if (request === selection.current) setError(`工具读取失败：${message(failure)}`);}
    finally {if (request === selection.current) setBusy(null);}
  }
  async function save(value:Record<string, unknown>) {
    if (!session || !editor || busy || pendingSave) return;
    const request = ++selection.current;
    setBusy('saving'); setError(null); setNotice(null);
    try {
      const saved = await session.saveTool(value as ToolDraft, editor.tool ? {id:editor.tool.id,version:editor.version} : undefined);
      if (request !== selection.current) return;
      setEditor({tool:saved.data, initial:editTool(saved.data), version:saved.version, revision:request});
      setTools(current => [...(current ?? []).filter(tool => tool.id !== saved.data.id), saved.data]);
      setDirty(false); setVerified(true); setTest(null); setNotice('工具已保存');
    } catch (failure) {
      if (request !== selection.current) return;
      if (rejectedSave(failure)) setError(`保存失败：${message(failure)}`);
      else {
        setPendingSave({draft:value as ToolDraft,toolId:editor.tool?.id}); setVerified(false);
        setError(`保存结果待确认：${message(failure)}。请先核实保存结果。`);
      }
    } finally {if (request === selection.current) setBusy(null);}
  }
  async function verifySave() {
    if (!session || !pendingSave) return;
    const request = ++selection.current;
    setBusy('loading');
    try {
      const loaded = await session.listTools();
      if (request !== selection.current) return;
      setTools(loaded.data);
      const matches = loaded.data.filter(tool => (!pendingSave.toolId || tool.id === pendingSave.toolId)
        && Object.entries(pendingSave.draft).every(([key,value]) => JSON.stringify(tool[key as keyof HttpToolDefinition]) === JSON.stringify(value)));
      if (matches.length !== 1) {setError('保存结果仍待确认，未找到唯一匹配的已保存定义。请核对列表后再次查询；先前请求仍可能迟到生效。'); return;}
      const tool = matches[0];
      setEditor({tool,initial:editTool(tool),version:loaded.version,revision:request});
      setPendingSave(null);setVerified(true);setDirty(false);setError(null);setNotice('已核实工具保存结果');
    } catch (failure) {if (request === selection.current) setError(`保存核实失败：${message(failure)}`);}
    finally {if (request === selection.current) setBusy(null);}
  }
  async function runTest(value:Record<string, unknown>) {
    if (!session || !editor?.tool) return;
    const request = ++selection.current;
    setBusy('testing'); setError(null); setNotice(null); setInputs(value);setTest(null);
    try {
      const current = await session.getTool(editor.tool.id);
      if (request !== selection.current) return;
      if (current.version !== editor.version) {
        setVerified(false); throw new Error('配置已经变化，请重新读取工具后测试');
      }
      const started = await session.startToolTest(editor.tool.id, value);
      if (request === selection.current) setTest(started.data);
    } catch (failure) {if (request === selection.current) {setError(`无法开始测试：${message(failure)}`); setBusy(null); setVerified(false);}}
  }
  async function create() {
    if (!session) return;
    const request = ++selection.current;
    setBusy('loading');setError(null);
    try {
      const candidate = await session.getToolNameCandidate();
      if (request !== selection.current) return;
      setEditor({tool:null,initial:{...structuredClone(emptyToolDraft),name:candidate.data},version:'',revision:request});
      setDirty(false);setTest(null);setNotice(null);
    } catch (failure) {if (request === selection.current) setError(`调用名称读取失败：${message(failure)}`);}
    finally {if (request === selection.current) setBusy(null);}
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
  const canTest = Boolean(editor?.tool && !busy && !dirty && verified && !pendingSave);
  return <div className="tool-registry">
    <ToolLibrarySidebar tools={tools} selectedId={editor?.tool?.id} busy={Boolean(busy)} verified={verified}
      connected={Boolean(session)} canCreate={Boolean(session && schema && verified && !busy && !pendingSave)}
      onCreate={() => void create()} onOpen={tool => void open(tool)} onReload={() => void reload()}/>
    <section className="tool-detail-view" aria-label="工具详情">
      <div className="tool-detail-toolbar" role="toolbar" aria-label="工具操作">
        {onNavigation && <button className="icon-button tool-navigation-toggle" aria-label="打开主导航" onClick={onNavigation}><SidebarSimple/></button>}
        <div className="tool-breadcrumb"><button aria-label="返回工具列表" disabled={Boolean(busy) || Boolean(pendingSave)}
          onClick={() => {setEditor(null);setTest(null);setDirty(false);setNotice(null);}}>工具库</button><span>/</span><span>HTTP 工具</span>
          {editor && <><span>/</span><strong>{editor.tool?.display_name || '新建工具'}</strong></>}</div>
        {editor && <div className="tool-toolbar-actions"><Button size="sm" variant="outline" disabled={!canTest}
          onClick={() => document.getElementById('tool-test-panel')?.scrollIntoView({behavior:'smooth',block:'start'})}><Play size={14}/>测试运行</Button>
          <Button size="sm" type="submit" form="tool-definition" disabled={!schema || Boolean(busy) || Boolean(pendingSave)}><FloppyDisk size={14}/>保存工具</Button></div>}
      </div>
      <div className="tool-detail-body">
        <div className="tool-page-notices" aria-label="工具页面提示">
          {error && <p role="alert" className="business-notice">{error}</p>}
          {notice && <p role="status">{notice}</p>}
          {pendingSave && <Button size="sm" variant="outline" disabled={Boolean(busy)} onClick={verifySave}>核实保存结果</Button>}
          {busy === 'loading' && tools !== null && <p role="status">正在读取工具库…</p>}
          {!verified && tools !== null && <p>读取尚未核实，不能使用旧配置开始测试。</p>}
        </div>
        {editor ? <>
          <ToolSummaryCard tool={editor.tool} initial={editor.initial} dirty={dirty}/>
          <div className="tool-editor-layout">
            {schema && <ToolDefinitionForm key={editor.revision} schema={schema} initial={{...editor.initial}} formId="tool-definition" externalSubmit
              disabled={Boolean(busy) || Boolean(pendingSave)} onSave={save} onEdited={() => {setDirty(true);setNotice(null);}}/>}
            <div className="tool-test-column">
              <section className="tool-panel" aria-label="快速测试调试" id="tool-test-panel"><header className="tool-panel-heading"><Play size={16}/><h2>快速测试调试</h2><span>{busy === 'testing' ? '测试中' : '真实 HTTP 请求'}</span></header>
                <div className="tool-panel-body">
                  {!editor.tool && <p className="tool-muted">请先保存工具，再执行测试。</p>}
                  {dirty && <p className="tool-muted">配置已修改，保存后再测试。{test?.result && '下方为修改前的测试结果。'}</p>}
                  {editor.tool && <ToolInputForm key={editor.revision} schema={editor.tool.input_schema} disabled={!canTest} onTest={runTest}/>}
                  {busy === 'testing' && <p role="status" className="tool-muted">测试中，正在请求接口并读取完整响应…</p>}
                  {busy === 'testing' && error && test && <Button size="sm" variant="outline" onClick={retryTest}>重新查询测试</Button>}
                  {test?.result ? <ToolTestResult key={test.test_id} result={test.result} inputs={inputs} onView={onView}/>
                    : <div className="tool-result-placeholder"><span>响应结果</span><pre>{busy === 'testing' ? '正在等待接口响应…' : '执行测试后，完整响应将在这里显示。'}</pre></div>}
                </div>
              </section>
              <section className="tool-panel tool-recent-test" aria-label="最近一次测试"><header className="tool-panel-heading"><ClockCounterClockwise size={16}/><h2>最近一次测试</h2><span>本页记录</span></header>
                <div className="tool-panel-body">{test ? <dl className="tool-test-facts"><dt>状态</dt><dd>{test.status === 'running' ? '测试中' : test.status === 'success' ? '测试成功' : test.status === 'error' ? '测试失败' : test.status === 'timeout' ? '测试超时' : '测试已取消'}</dd>
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
  </div>;
}
