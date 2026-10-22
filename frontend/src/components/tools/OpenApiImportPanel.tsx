import {useCallback, useEffect, useImperativeHandle, useRef, useState, type Ref} from 'react';
import type {RJSFSchema} from '@rjsf/utils';
import {FileArrowUp, FloppyDisk, SidebarSimple} from '@phosphor-icons/react';
import type {BackendSession} from '../../backend-client';
import type {AnyToolDefinition, HttpToolDraft, ToolLibraryRead} from '../../tool-library';
import {nameOpenApiOperations, openApiConfigurationErrors, type OpenApiOperation} from '../../openapi-import';
import {saveWasRejected} from '../../tool-save-errors';
import {Button} from '../ui/button';
import {Textarea} from '../ui/textarea';
import {Overlay} from '../Overlay';
import {ToolDefinitionForm} from './ToolDefinitionForm';
import type {ToolsWorkspaceHandle} from './ToolsWorkspace';

const message=(error:unknown) => error instanceof Error ? error.message : String(error);
export function OpenApiImportPanel({session,schema,occupiedNames,onLibrary,onOpen,onClose,onNavigation,ref}: {
  session:BackendSession; schema:RJSFSchema; occupiedNames:string[]; onLibrary:(library:ToolLibraryRead) => void;
  onOpen:(tool:AnyToolDefinition) => void; onClose:() => void; onNavigation?:() => void; ref?:Ref<ToolsWorkspaceHandle>;
}) {
  const [documentText,setDocumentText]=useState('');
  const [parsedDocument,setParsedDocument]=useState('');
  const [operations,setOperations]=useState<OpenApiOperation[]>([]);
  const [selected,setSelected]=useState<string[]>([]);
  const [activeKey,setActiveKey]=useState<string | null>(null);
  const [revision,setRevision]=useState(0);
  const [title,setTitle]=useState('');
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState<string | null>(null);
  const [notice,setNotice]=useState<string | null>(null);
  const [savedIds,setSavedIds]=useState<string[]>([]);
  const [savedTools,setSavedTools]=useState<AnyToolDefinition[]>([]);
  const [saveOutcomeUnknown,setSaveOutcomeUnknown]=useState(false);
  const [leaveAction,setLeaveAction]=useState<(() => void) | null>(null);
  const [replacePreview,setReplacePreview]=useState(false);
  const sequence=useRef(0);
  const leaveAfterSave=useRef(false);
  const active=operations.find(item => item.key === activeKey);
  const locked=busy || saveOutcomeUnknown || savedIds.length > 0;
  const dirty=Boolean(documentText || operations.length) && !savedIds.length;
  const outdated=documentText !== parsedDocument;
  const chosen=operations.filter(item => selected.includes(item.key));
  function configurationErrors(item:OpenApiOperation) {
    const errors=openApiConfigurationErrors(item,schema);
    if (!savedIds.length && (occupiedNames.includes(item.definition.name) || chosen.some(other => other.key !== item.key && other.definition.name === item.definition.name))) errors.push('调用名称与已有工具或所选接口重名');
    return errors;
  }
  const canSave=!locked && !outdated && chosen.length > 0 && chosen.every(item => !configurationErrors(item).length);
  useEffect(() => () => {sequence.current++;},[]);
  useEffect(() => {
    if (!dirty) return;
    const warn=(event:BeforeUnloadEvent) => {event.preventDefault();event.returnValue='';};
    window.addEventListener('beforeunload',warn);
    return () => window.removeEventListener('beforeunload',warn);
  },[dirty]);
  function requestLeave(action:() => void) {
    if (busy) {setNotice('当前操作尚未完成，请完成后再离开。');return;}
    if (dirty || saveOutcomeUnknown) {setLeaveAction(() => action);leaveAfterSave.current=false;}
    else action();
  }
  useImperativeHandle(ref,() => ({requestLeave}));
  function finishLeave() {const action=leaveAction;setLeaveAction(null);leaveAfterSave.current=false;action?.();}
  async function parse() {
    if (!documentText.trim() || locked) return;
    const request=++sequence.current;setBusy(true);setError(null);setNotice(null);setReplacePreview(false);
    try {
      const result=await session.previewOpenApi(documentText);
      if (request !== sequence.current) return;
      const candidates=nameOpenApiOperations(result.data,occupiedNames);
      setOperations(candidates);setParsedDocument(documentText);setSelected([]);
      setActiveKey(candidates[0]?.key ?? null);setRevision(value => value+1);
      setTitle(`${result.data.title || 'OpenAPI 文档'} · ${result.data.openapi}`);
      setNotice(candidates.length ? `已解析 ${candidates.length} 个接口，请勾选并补齐配置。` : '文档中没有可预览的接口。');
    } catch (failure) {if (request === sequence.current) setError(`解析失败：${message(failure)}。文档与原预览草稿已保留。`);}
    finally {if (request === sequence.current) setBusy(false);}
  }
  async function upload(file:File | undefined) {
    if (!file || locked) return;
    if (file.size > 2_000_000) {setError('文档不能超过 2 MB');return;}
    const request=++sequence.current;setBusy(true);setError(null);
    try {
      const text=await new Promise<string>((resolve,reject) => {
        const reader=new FileReader();reader.onload=() => resolve(String(reader.result));
        reader.onerror=() => reject(reader.error ?? new Error('文件读取失败'));reader.readAsText(file);
      });
      if (request === sequence.current) {setDocumentText(text);setNotice(`已读取 ${file.name}，请解析文档。`);}
    } catch (failure) {if (request === sequence.current) setError(`文件读取失败：${message(failure)}`);}
    finally {if (request === sequence.current) setBusy(false);}
  }
  async function readSaved(ids=savedIds) {
    const request=++sequence.current;setBusy(true);setError(null);
    try {
      const [library,...details]=await Promise.all([session.listTools(),...ids.map(id => session.getTool(id))]);
      if (request !== sequence.current) return;
      onLibrary(library);setSavedTools(details.map(detail => detail.data));
      setNotice(`已保存 ${ids.length} 个 HTTP 工具，可打开详情编辑和测试。`);
      if (leaveAfterSave.current) finishLeave();
    } catch (failure) {if (request === sequence.current) setError(`工具已保存，列表或详情读取失败：${message(failure)}。请重新读取，无需再次导入。`);}
    finally {if (request === sequence.current) setBusy(false);}
  }
  async function save() {
    if (!canSave) return;
    const request=++sequence.current;setBusy(true);setError(null);setNotice(null);
    let ids:string[];
    try {
      const result=await session.importOpenApiTools(parsedDocument,chosen.map(item => ({operation_key:item.key,definition:item.definition,security_option:item.security_option})));
      ids=result.data.map(item => item.id);
    } catch (failure) {
      if (request !== sequence.current) return;
      if (saveWasRejected(failure)) setError(`保存失败：${message(failure)}。所选项与配置草稿已保留。`);
      else {setSaveOutcomeUnknown(true);setError(`保存结果不确定：${message(failure)}。请勿重复导入，可放弃草稿并重读工具库查看结果。`);}
      setBusy(false);return;
    }
    if (request !== sequence.current) return;
    setSavedIds(ids);setNotice('工具已保存，正在读取详情…');
    await readSaved(ids);
  }
  async function abandonAndReload() {
    const request=++sequence.current;setBusy(true);setError(null);
    try {
      const library=await session.listTools();
      if (request !== sequence.current) return;
      onLibrary(library);setSaveOutcomeUnknown(false);setDocumentText('');setParsedDocument('');setOperations([]);setSelected([]);setActiveKey(null);
      setNotice('已放弃草稿并重读工具库；此前保存结果仍不确定，请查看已保存配置。');
      if (leaveAfterSave.current || leaveAction) finishLeave();
    } catch (failure) {if (request === sequence.current) setError(`工具库读取失败：${message(failure)}。草稿已保留。`);}
    finally {if (request === sequence.current) setBusy(false);}
  }
  const validateName=useCallback(async (name:string,signal:AbortSignal) => (await session.validateToolName(name,undefined,signal)).data,[session]);
  function updateActive(value:Record<string,unknown>) {
    setOperations(current => current.map(item => item.key === activeKey ? {...item,definition:value as HttpToolDraft} : item));
    setError(null);
  }
  return <section className="tool-detail-view" aria-label="OpenAPI 导入">
    <div className="tool-detail-toolbar openapi-toolbar" role="toolbar" aria-label="OpenAPI 操作">
      {onNavigation && <button className="icon-button tool-navigation-toggle" aria-label="打开主导航" onClick={onNavigation}><SidebarSimple/></button>}
      <div className="tool-breadcrumb"><button onClick={() => requestLeave(onClose)}>工具与技能</button><span>/</span><strong>OpenAPI 导入</strong></div>
      <div className="tool-toolbar-actions"><Button size="sm" disabled={!canSave} onClick={save}><FloppyDisk size={14}/>保存所选工具</Button></div>
    </div>
    <div className="tool-detail-body">
      <section className="tool-summary-card"><span className="tool-summary-icon"><FileArrowUp size={24}/></span><div className="tool-summary-information"><div className="tool-summary-title"><h1>从 OpenAPI 导入 HTTP 工具</h1></div><p>{title || '上传或粘贴单份 JSON／YAML · OpenAPI 3.0.x／3.1.x'}</p><p className="tool-muted">解析、预览和保存均不会调用接口；再次导入创建新工具。</p></div></section>
      <div className="tool-page-notices">
        {error && !leaveAction && <p role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}
        {busy && <p role="status">正在处理…</p>}
        {savedIds.length > 0 && !leaveAction && <><p>已保存工具 ID：{savedIds.join('、')}</p><Button variant="outline" size="sm" disabled={busy} onClick={() => void readSaved()}>重新读取已保存工具</Button>
          {savedTools.map(tool => <Button key={tool.id} variant="outline" size="sm" onClick={() => onOpen(tool)}>编辑工具 {tool.display_name}</Button>)}</>}
        {saveOutcomeUnknown && !leaveAction && <Button variant="outline" disabled={busy} onClick={abandonAndReload}>放弃草稿并重读工具库</Button>}
        {outdated && operations.length > 0 && <p role="status">文档已修改，请重新解析后保存；原预览修改暂时保留。</p>}
      </div>
      <div className="tool-editor-layout openapi-import-layout">
        <div className="tool-definition-sections">
          <section className="tool-panel" aria-label="导入文档"><header className="tool-panel-heading"><FileArrowUp size={16}/><h2>导入文档</h2><span>JSON / YAML</span></header>
            <div className="tool-panel-body"><label className="openapi-upload">上传 JSON／YAML 文件<input aria-label="上传 OpenAPI 文档" type="file" accept=".json,.yaml,.yml,application/json,application/yaml,text/yaml" disabled={locked} onChange={event => {void upload(event.target.files?.[0]);event.target.value='';}}/></label>
              <label htmlFor="openapi-document">OpenAPI 文档</label><Textarea id="openapi-document" value={documentText} disabled={locked} rows={12} placeholder="在这里粘贴 OpenAPI JSON 或 YAML…" onChange={event => {setDocumentText(event.target.value);setError(null);}}/>
              <p className="tool-muted">支持文档内部请求引用、嵌套 JSON、可空结构及 Bearer／API Key 认证。超出支持范围的接口会逐项说明原因。</p>
              <Button size="sm" disabled={locked || !documentText.trim()} onClick={() => operations.length ? setReplacePreview(true) : void parse()}>解析文档</Button></div>
          </section>
          <section className="tool-panel" aria-label="接口选择"><header className="tool-panel-heading"><h2>接口选择</h2><span>{selected.length} / {operations.length} 已选</span></header><div className="tool-panel-body">
            {!operations.length && <p className="tool-muted">解析后显示接口；只保存勾选项。</p>}
            <ul className="openapi-operation-list">{operations.map(item => {
              const reasons=configurationErrors(item);
              return <li key={item.key} className={item.key === activeKey ? 'active' : ''}>
                <label><input type="checkbox" aria-label={`选择 ${item.key}`} disabled={locked || item.errors.length > 0} checked={selected.includes(item.key)} onChange={event => {
                  setSelected(current => event.target.checked ? [...current,item.key] : current.filter(key => key !== item.key));setActiveKey(item.key);setRevision(value => value+1);
                }}/><span className="tool-type-tag">{item.method}</span><code>{item.path}</code></label>
                <Button size="sm" variant="ghost" disabled={busy} aria-label={`预览 ${item.key}`} onClick={() => {setActiveKey(item.key);setRevision(value => value+1);}}>{item.definition.display_name || item.name_hint}</Button>
                <p className="tool-muted">{savedIds.length && selected.includes(item.key) ? '已保存' : item.errors.length ? '未支持' : reasons.length ? '需要补配置' : '可保存'} · {item.definition.name}</p>
                {reasons.map((reason,index) => <p key={index} className="tool-muted">{reason}</p>)}
              </li>;
            })}</ul></div></section>
        </div>
        <div className="tool-test-column" aria-label="接口预览">
          {active ? <><section className="tool-panel"><header className="tool-panel-heading"><h2>接口预览与补配置</h2><span>{active.method}</span></header><div className="tool-panel-body"><code>{active.path}</code>
            {active.servers.length > 0 && <label>服务器候选<select aria-label="服务器候选" disabled={locked || active.errors.length > 0} value="" onChange={event => {
              const server=active.servers[Number(event.target.value)];
              if (server) {updateActive({...active.definition,url:server.url.replace(/\/$/,'')+active.path});setRevision(value => value+1);}
            }}><option value="" disabled>选择来源服务器或手工修改请求地址</option>{active.servers.map((server,index) => <option key={index} value={index}>{server.description ? `${server.description} · ` : ''}{server.url}</option>)}</select></label>}
            {active.security_options && <label>来源认证方案<select aria-label="来源认证方案" disabled={locked || active.errors.length > 0} value={active.security_option ?? ''} onChange={event => {
              const option=active.security_options?.find(item => item.id === event.target.value);
              if (!option || option.errors.length) return;
              setOperations(current => current.map(item => item.key === active.key ? {...item,security_option:option.id,definition:{...item.definition,auth:option.auth.map(binding => {
                const previous=item.definition.auth?.find(saved => saved.id === binding.id && saved.kind === binding.kind && saved.location === binding.location && saved.name === binding.name);
                return {...binding,value:previous?.value ?? ''};
              })}} : item));
              setRevision(value => value+1);setError(null);
            }}>{!active.security_option && <option value="">没有受支持的认证方案</option>}{active.security_options.map(option => <option key={option.id} value={option.id} disabled={option.errors.length > 0}>{option.label}{option.errors.length ? '（未支持）' : ''}</option>)}</select></label>}
            {active.security_options?.flatMap(option => option.errors).map((reason,index) => <p key={`security-${index}`} className="tool-muted">{active.key} {reason}</p>)}
            {active.errors.length > 0 && <details><summary>OpenAPI 原始来源</summary><pre className="openapi-source">{JSON.stringify(active.definition.openapi_source,null,2)}</pre></details>}
            {active.warnings.map(warning => <p key={warning} className="tool-muted">{warning}</p>)}</div></section>
            <ToolDefinitionForm key={`${active.key}-${revision}`} schema={schema} initial={{...active.definition}} disabled={locked || active.errors.length > 0}
              externalSubmit validateName={validateName} onSave={() => {}} onEdited={updateActive}/>
          </> : <section className="tool-panel"><div className="tool-panel-body"><h2>接口预览</h2><p className="tool-muted">解析文档后选择接口，查看方法、地址、参数和缺配置原因。保存后可在工具详情进行真实测试。</p></div></section>}
        </div>
      </div>
    </div>
    {replacePreview && <Overlay title="重新解析文档" onClose={() => setReplacePreview(false)}><div className="tool-confirmation"><p>重新解析会替换当前预览配置和勾选项，原工具库不受影响。</p><div className="tool-actions"><Button onClick={() => void parse()}>确认重新解析</Button><Button variant="outline" onClick={() => setReplacePreview(false)}>继续编辑</Button></div></div></Overlay>}
    {leaveAction && <Overlay title={saveOutcomeUnknown ? '保存结果不确定' : savedIds.length ? '工具已保存' : '未保存的导入草稿'} onClose={() => {if (!busy) {setLeaveAction(null);leaveAfterSave.current=false;}}}>
      <div className="tool-confirmation"><p>{saveOutcomeUnknown ? '没有收到保存响应，请重读工具库核实，避免重复导入。' : savedIds.length ? '保存已成功，可以重新读取详情或直接离开。' : '文档、接口选择及预览配置仅在本页内存中。离开后不再保留。'}</p>{error && <p role="alert">{error}</p>}
        <div className="tool-actions">{saveOutcomeUnknown ? <Button disabled={busy} onClick={abandonAndReload}>放弃草稿并重读工具库</Button> : savedIds.length ? <><Button disabled={busy} onClick={() => void readSaved()}>重新读取已保存工具</Button><Button disabled={busy} onClick={finishLeave}>已保存，直接离开</Button></> : <><Button disabled={!canSave} onClick={() => {leaveAfterSave.current=true;void save();}}>保存并离开</Button><Button variant="outline" disabled={busy} onClick={finishLeave}>放弃修改</Button></>}
          <Button variant="outline" disabled={busy} onClick={() => {setLeaveAction(null);leaveAfterSave.current=false;}}>继续编辑</Button></div>
      </div>
    </Overlay>}
  </section>;
}
