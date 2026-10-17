import { useEffect, useMemo, useRef, useState } from 'react';
import type { FieldProps, ObjectFieldTemplateProps, RJSFSchema } from '@rjsf/utils';
import { BracketsCurly, GearSix } from '@phosphor-icons/react';
import { Button } from '../ui/button';
import { SchemaForm } from './SchemaForm';
import { InputSchemaEditor } from './InputSchemaEditor';
import { HttpAuthEditor } from './HttpAuthEditor';
import { PythonSourceEditor } from './PythonSourceEditor';
import { analyzePythonSource, type PythonSourceAnalysis } from '../../python-source';
import { syncHttpMappings, type HttpParameterMapping } from '../../tool-library';
import type { ToolNameValidation } from '../../tool-library';

function PythonParameters({registry,disabled,readonly}:FieldProps) {
  const {pythonAnalysis:analysis,backendOnly,onBackendValidation}=registry.formContext as {
    pythonAnalysis:PythonSourceAnalysis; backendOnly:boolean; onBackendValidation:() => void;
  };
  return <section aria-label="源码参数预览" className="tool-python-preview">
    <p className="tool-muted">名称、类型、必填性和默认值来自 main。可省略与允许 null 分开；测试不会自动填入默认值。</p>
    {analysis.diagnostics.map((diagnostic,index) => <p role="alert" key={index}>
      第 {analysis.source.slice(0,diagnostic.from).split('\n').length} 行 · {diagnostic.code}：{diagnostic.message}
    </p>)}
    {analysis.canAskBackend && !backendOnly && <><p className="tool-muted">本地无法确认这段源码。可以继续编辑，或交给后端校验；不会沿用旧参数结构。</p>
      <Button type="button" size="sm" variant="outline" disabled={disabled || readonly} onClick={onBackendValidation}>交给后端校验</Button></>}
    {backendOnly && <p role="status">保存和测试将由后端校验当前源码。测试参数请使用 JSON 填写。</p>}
    {analysis.input_schema && !backendOnly && <><p className="tool-muted">本地检查完成，保存和测试时由后端复核。</p>
      <table><thead><tr><th>参数</th><th>类型</th><th>提供要求</th><th>函数默认值</th></tr></thead>
      <tbody>{analysis.parameters.map(parameter => <tr key={parameter.name}>
        <td><code>{parameter.name}</code></td><td>{parameter.type}</td><td>{parameter.required ? '必填' : '可省略'}</td>
        <td><code>{parameter.default_expression ?? '无'}</code></td></tr>)}</tbody></table>
      {analysis.parameters.length === 0 && <p>main 无参数，实际输入为 {'{}'}。</p>}</>}
  </section>;
}

function DefinitionSections({properties, registry}: ObjectFieldTemplateProps) {
  const structureFields = new Set(['input_schema','output_schema']);
  return <div className="tool-definition-sections">
    <section className="tool-panel" aria-label="工具配置"><header className="tool-panel-heading"><GearSix size={16}/><h2>工具配置</h2><span>{registry.formContext?.python ? 'Python' : 'HTTP'}</span></header>
      <div className="tool-config-fields">{properties.filter(property => !structureFields.has(property.name)).map(property =>
        <div key={property.name} className={`tool-config-field tool-field-${property.name}`}>{property.content}</div>)}</div>
    </section>
    <section className="tool-panel tool-schema-panel" aria-label="输入与输出结构"><header className="tool-panel-heading"><BracketsCurly size={16}/><h2>输入与输出结构</h2><span>JSON Schema</span></header>
      <div className="tool-schema-fields">{properties.filter(property => structureFields.has(property.name)).map(property =>
        <div key={property.name}>{property.content}</div>)}</div>
    </section>
  </div>;
}

export function ToolDefinitionForm({schema, initial, enabled, disabled = false, onSave, onEdited, onInvalid, formId, externalSubmit = false, suggestName, validateName, onSourceAnalysis}: {
  schema: RJSFSchema; initial: Record<string, unknown>; enabled?:boolean; disabled?: boolean;
  onSave: (value: Record<string, unknown>) => void; onEdited?: (value:Record<string,unknown>) => void;
  onInvalid?:(message:string) => void;
  formId?:string; externalSubmit?:boolean;
  suggestName?: (displayName: string) => string;
  validateName?: (name: string, signal: AbortSignal) => Promise<ToolNameValidation>;
  onSourceAnalysis?:(analysis:PythonSourceAnalysis) => void;
}) {
  const python=initial.kind === 'python';
  function editable(data:Record<string,unknown>) {
    if (!python) return data;
    const {input_schema, ...draft}=data;
    return draft;
  }
  const [value, setValue] = useState(() => editable(initial));
  const [backendSource, setBackendSource] = useState<string | null>(null);
  const source=typeof value.source === 'string' ? value.source : '';
  const localAnalysis=useMemo(() => python ? analyzePythonSource(source) : null,[python,source]);
  const backendOnly=Boolean(localAnalysis?.canAskBackend && backendSource === source);
  const analysis=useMemo(() => localAnalysis && backendOnly ? {...localAnalysis,input_schema:{}} : localAnalysis,[localAnalysis,backendOnly]);
  useEffect(() => {
    if (analysis) onSourceAnalysis?.(analysis);
  },[analysis,onSourceAnalysis]);
  const manualName = useRef(false);
  const name = typeof value.name === 'string' ? value.name : '';
  const [nameCheck, setNameCheck] = useState<{name:string; result?:ToolNameValidation; error?:string} | null>(null);
  useEffect(() => {
    if (!validateName || disabled) return;
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      validateName(name, controller.signal).then(result => {
        if (!controller.signal.aborted) setNameCheck({name,result});
      }).catch(() => {
        if (!controller.signal.aborted) setNameCheck({name,error:'调用名称校验暂不可用，保存时将再次校验。'});
      });
    }, 250);
    return () => {window.clearTimeout(timer); controller.abort();};
  }, [name, validateName, disabled]);
  const nameError = nameCheck?.name === name && nameCheck.result?.valid === false
    ? nameCheck.result.message ?? '调用名称无效' : null;
  return <SchemaForm className="tool-definition-form" id={formId} idPrefix="tool-config" schema={schema}
    fields={{InputSchema:InputSchemaEditor,HttpAuth:HttpAuthEditor,PythonParameters}}
    widgets={{PythonSource:PythonSourceEditor}}
    formContext={{python,pythonAnalysis:analysis,backendOnly,onBackendValidation:() => setBackendSource(source)}}
    templates={{ObjectFieldTemplate:DefinitionSections}}
    extraErrors={nameError ? {name:{__errors:[nameError]}} : undefined} extraErrorsBlockSubmit
    formData={enabled === undefined ? value : {...value,enabled}} disabled={disabled} uiSchema={{
      'ui:submitButtonOptions':{norender:externalSubmit},
      'ui:order':(python ? ['display_name','name','description','kind','source','timeout_seconds','enabled','input_schema','output_schema']
        : ['display_name','name','description','kind','method','url','headers','parameters','auth','timeout_seconds','enabled','input_schema','output_schema']).filter(field => schema.properties?.[field]),
      kind:{'ui:widget':'hidden'}, description:{'ui:widget':'textarea'},
      source:{'ui:widget':'PythonSource','ui:help':'固定顶层同步 main；当前支持 str/int/float/bool 普通具名参数。Tab 缩进，Esc 后按 Tab 离开编辑器。仅测试或执行时以本机权限运行。'},
      headers:{'ui:field':'JsonSchema','ui:help':'固定请求头：JSON 对象；请求体仅支持 application/json。'},
      parameters:{'ui:field':'JsonSchema','ui:help':'每项填写 location、input_name、name；query 使用 form（explode 默认 true），path/headers 使用 simple。'},
      auth:{'ui:field':'HttpAuth'},
      name:{'ui:help':nameCheck?.name === name && nameCheck.error ? nameCheck.error
        : '1–64 个英文字母、数字或下划线，以字母或下划线开头；手动修改后保留。'},
      input_schema:{'ui:field':python ? 'PythonParameters' : 'InputSchema'}, output_schema:{'ui:field':'JsonSchema'},
    }} onChange={event => {
      const next = editable({...event.formData});
      if (python && next.source !== value.source) setBackendSource(null);
      if (schema.properties?.parameters && JSON.stringify(next.input_schema) !== JSON.stringify(value.input_schema)
        && next.input_schema && typeof next.input_schema === 'object' && !Array.isArray(next.input_schema)
        && Array.isArray(next.parameters) && next.parameters.every(item => item && typeof item === 'object'
          && ['path','query','headers'].includes(item.location) && typeof item.input_name === 'string' && typeof item.name === 'string'))
        next.parameters=syncHttpMappings(next.input_schema as RJSFSchema,next.parameters as HttpParameterMapping[]);
      if (next.name !== value.name) manualName.current = true;
      if (suggestName && !manualName.current && next.display_name !== value.display_name)
        next.name = suggestName(typeof next.display_name === 'string' ? next.display_name : '');
      if (next.name !== value.name) setNameCheck(null);
      setValue(next); onEdited?.(next);
    }} onError={errors => onInvalid?.(errors.map(error => error.stack).join('；'))} onSubmit={event => {
      if (!python || analysis?.input_schema) onSave(editable({...event.formData}));
    }}>
    {!externalSubmit && <Button type="submit" disabled={disabled || Boolean(python && !analysis?.input_schema)}>保存工具</Button>}
  </SchemaForm>;
}
