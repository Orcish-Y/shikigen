import { useEffect, useMemo, useRef, useState } from 'react';
import type { FieldProps, ObjectFieldTemplateProps, RJSFSchema } from '@rjsf/utils';
import { BracketsCurly, GearSix } from '@phosphor-icons/react';
import { Button } from '../ui/button';
import { SchemaForm } from './SchemaForm';
import { schemaValidatorFor } from '../../schema-validation';
import { InputSchemaEditor } from './InputSchemaEditor';
import { HttpAuthEditor } from './HttpAuthEditor';
import { PythonSourceEditor } from './PythonSourceEditor';
import { PythonParameters } from './PythonParameters';
import { isSchema, pythonSchemaErrors, syncPythonInputSchema, type PythonSchemaChange } from '../../python-schema';
import { analyzePythonSource, type PythonSourceAnalysis } from '../../python-source';
import { syncHttpMappings, type HttpParameterMapping } from '../../tool-library';
import type { ToolNameValidation } from '../../tool-library';

function OpenApiSource({formData}:FieldProps) {
  return formData ? <details className="tool-panel-body"><summary>OpenAPI 原始来源</summary><pre className="openapi-source">{JSON.stringify(formData,null,2)}</pre></details> : null;
}
function DefinitionSections({properties, registry}: ObjectFieldTemplateProps) {
  const structureFields = new Set(['input_schema','output_schema','openapi_source']);
  return <div className="tool-definition-sections">
    <section className="tool-panel" aria-label="工具配置"><header className="tool-panel-heading"><GearSix size={16}/><h2>工具配置</h2><span>{registry.formContext?.python ? 'Python' : registry.formContext?.mcp ? 'MCP' : 'HTTP'}</span></header>
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
  const mcp=initial.kind === 'mcp';
  const [value, setValue] = useState(() => python && initial.input_schema === undefined
    ? {...initial,input_schema:analyzePythonSource(typeof initial.source === 'string' ? initial.source : '').input_schema ?? {}} : initial);
  const [changes,setChanges]=useState<PythonSchemaChange[]>([]);
  const [backendSource, setBackendSource] = useState<string | null>(null);
  const source=typeof value.source === 'string' ? value.source : '';
  const localAnalysis=useMemo(() => python ? analyzePythonSource(source) : null,[python,source]);
  const lastParsed=useRef(localAnalysis);
  const backendOnly=Boolean(localAnalysis?.canAskBackend && backendSource === source);
  const analysis=useMemo(() => {
    if (!localAnalysis) return null;
    if (backendOnly) return {...localAnalysis,input_schema:{},backendValidationRequested:true};
    const candidate=value.input_schema;
    const compiled=isSchema(candidate) ? schemaValidatorFor(candidate).rawValidation(candidate,{}) : null;
    const errors=compiled?.validationError ? [compiled.validationError.message] : pythonSchemaErrors(localAnalysis,candidate);
    if (!isSchema(candidate)) errors.push('输入结构 JSON 无效，请修正原文');
    if (changes.some(change => change.review)) errors.push('源码存在待确认变更');
    return {...localAnalysis,input_schema:localAnalysis.input_schema && !errors.length && isSchema(candidate) ? candidate : null,
      diagnostics:[...localAnalysis.diagnostics,...errors.map(message => ({from:0,to:0,severity:'error' as const,code:'python_schema',message}))]};
  },[localAnalysis,backendOnly,value.input_schema,changes]);
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
    fields={{InputSchema:InputSchemaEditor,HttpAuth:HttpAuthEditor,PythonParameters,OpenApiSource}}
    widgets={{PythonSource:PythonSourceEditor}}
    formContext={{python,mcp,pythonAnalysis:analysis,localPythonAnalysis:localAnalysis,backendOnly,onBackendValidation:() => setBackendSource(source),
      pythonChanges:changes,onConfirmPythonChanges:() => setChanges(current => current.map(change => ({...change,review:false})))}}
    templates={{ObjectFieldTemplate:DefinitionSections}}
    extraErrors={nameError ? {name:{__errors:[nameError]}} : undefined} extraErrorsBlockSubmit
    formData={enabled === undefined ? value : {...value,enabled}} disabled={disabled} uiSchema={{
      'ui:submitButtonOptions':{norender:externalSubmit},
      'ui:order':(python ? ['display_name','name','description','kind','source','timeout_seconds','enabled','input_schema','output_schema']
        : mcp ? ['display_name','name','description','kind','connection_id','remote_name','timeout_seconds','enabled','input_schema','output_schema','source_tool']
        : ['display_name','name','description','kind','method','url','headers','parameters','auth','timeout_seconds','enabled','input_schema','output_schema','openapi_source']).filter(field => schema.properties?.[field]),
      kind:{'ui:widget':'hidden'}, description:{'ui:widget':'textarea'},
      source:{'ui:widget':'PythonSource','ui:help':'顶层同步 main，支持普通具名、仅关键字和 **kwargs；未知类型请在参数区补齐。Tab 缩进，Esc 后按 Tab 离开编辑器。仅测试或执行时以本机权限运行。'},
      headers:{'ui:field':'JsonSchema','ui:help':'固定请求头：JSON 对象；请求体仅支持 application/json。'},
      parameters:{'ui:field':'JsonSchema','ui:help':'每项填写 location、input_name、name；query 使用 form（explode 默认 true），path/headers 使用 simple。'},
      auth:{'ui:field':'HttpAuth'},
      openapi_source:{'ui:field':'OpenApiSource'},
      name:{'ui:help':nameCheck?.name === name && nameCheck.error ? nameCheck.error
        : '1–64 个英文字母、数字或下划线，以字母或下划线开头；手动修改后保留。'},
      connection_id:{'ui:readonly':true},remote_name:{'ui:readonly':true},source_tool:{'ui:field':'JsonSchema','ui:readonly':true},
      input_schema:{'ui:field':python ? 'PythonParameters' : mcp ? 'JsonSchema' : 'InputSchema','ui:readonly':mcp}, output_schema:{'ui:field':'JsonSchema','ui:readonly':mcp},
    }} onChange={event => {
      const next = {...event.formData};
      if (python && next.source !== value.source) {
        setBackendSource(null);
        const current=analyzePythonSource(typeof next.source === 'string' ? next.source : '');
        if (current.input_schema) {
          if (lastParsed.current?.input_schema) {
            const synchronized=syncPythonInputSchema(lastParsed.current,current,value.input_schema);
            next.input_schema=synchronized.schema;
            setChanges(existing => [...existing,...synchronized.changes]);
          } else next.input_schema=current.input_schema;
          lastParsed.current=current;
        }
      }
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
      if (!python || analysis?.input_schema) {
        const payload={...event.formData};
        if (backendOnly) delete payload.input_schema;
        onSave(payload);
      }
    }}>
    {!externalSubmit && <Button type="submit" disabled={disabled || Boolean(python && !analysis?.input_schema)}>保存工具</Button>}
  </SchemaForm>;
}
