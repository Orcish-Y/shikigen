import { useEffect, useRef, useState } from 'react';
import type { ObjectFieldTemplateProps, RJSFSchema } from '@rjsf/utils';
import { BracketsCurly, GearSix } from '@phosphor-icons/react';
import { Button } from '../ui/button';
import { SchemaForm } from './SchemaForm';
import { InputSchemaEditor } from './InputSchemaEditor';
import { syncHttpMappings, type HttpParameterMapping } from '../../tool-library';
import type { ToolNameValidation } from '../../tool-library';

function DefinitionSections({properties}: ObjectFieldTemplateProps) {
  const structureFields = new Set(['input_schema','output_schema']);
  return <div className="tool-definition-sections">
    <section className="tool-panel" aria-label="工具配置"><header className="tool-panel-heading"><GearSix size={16}/><h2>工具配置</h2><span>HTTP</span></header>
      <div className="tool-config-fields">{properties.filter(property => !structureFields.has(property.name)).map(property =>
        <div key={property.name} className={`tool-config-field tool-field-${property.name}`}>{property.content}</div>)}</div>
    </section>
    <section className="tool-panel tool-schema-panel" aria-label="输入与输出结构"><header className="tool-panel-heading"><BracketsCurly size={16}/><h2>输入与输出结构</h2><span>JSON Schema</span></header>
      <div className="tool-schema-fields">{properties.filter(property => structureFields.has(property.name)).map(property =>
        <div key={property.name}>{property.content}</div>)}</div>
    </section>
  </div>;
}

export function ToolDefinitionForm({schema, initial, disabled = false, onSave, onEdited, onInvalid, formId, externalSubmit = false, suggestName, validateName}: {
  schema: RJSFSchema; initial: Record<string, unknown>; disabled?: boolean;
  onSave: (value: Record<string, unknown>) => void; onEdited?: (value:Record<string,unknown>) => void;
  onInvalid?:(message:string) => void;
  formId?:string; externalSubmit?:boolean;
  suggestName?: (displayName: string) => string;
  validateName?: (name: string, signal: AbortSignal) => Promise<ToolNameValidation>;
}) {
  const [value, setValue] = useState(initial);
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
    fields={{InputSchema:InputSchemaEditor}}
    templates={{ObjectFieldTemplate:DefinitionSections}}
    extraErrors={nameError ? {name:{__errors:[nameError]}} : undefined} extraErrorsBlockSubmit
    formData={value} disabled={disabled} uiSchema={{
      'ui:submitButtonOptions':{norender:externalSubmit},
      'ui:order':['display_name','name','description','kind','method','url','headers','parameters','timeout_seconds','enabled','input_schema','output_schema'],
      kind:{'ui:widget':'hidden'}, description:{'ui:widget':'textarea'},
      headers:{'ui:field':'JsonSchema','ui:help':'固定请求头：JSON 对象；请求体仅支持 application/json。'},
      parameters:{'ui:field':'JsonSchema','ui:help':'每项填写 location、input_name、name；query 使用 form（explode 默认 true），path/headers 使用 simple。'},
      name:{'ui:help':nameCheck?.name === name && nameCheck.error ? nameCheck.error
        : '1–64 个英文字母、数字或下划线，以字母或下划线开头；手动修改后保留。'},
      input_schema:{'ui:field':'InputSchema'}, output_schema:{'ui:field':'JsonSchema'},
    }} onChange={event => {
      const next = {...event.formData};
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
    }} onError={errors => onInvalid?.(errors.map(error => error.stack).join('；'))} onSubmit={event => onSave({...event.formData})}>
    {!externalSubmit && <Button type="submit" disabled={disabled}>保存工具</Button>}
  </SchemaForm>;
}
