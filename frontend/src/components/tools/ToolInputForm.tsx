import { useState } from 'react';
import type { RJSFSchema } from '@rjsf/utils';
import { SchemaForm, schemaValidatorFor } from './SchemaForm';
import type { ErrorObject } from 'ajv';
import { Button } from '../ui/button';
import { Textarea } from '../ui/textarea';
import { Play } from '@phosphor-icons/react';
import { hasNonFiniteNumber, parseJson } from './JsonEditor';

function advancedReason(schema:RJSFSchema):string | null {
  if (schema.$schema && !['http://json-schema.org/draft-07/schema#','https://json-schema.org/draft-07/schema#','https://json-schema.org/draft/2020-12/schema'].includes(schema.$schema))
    return '此 schema 方言无法渲染，使用 JSON 输入并由后端诊断。';
  function needsJson(node:unknown):boolean {
    if (typeof node === 'boolean' || !node || typeof node !== 'object') return true;
    const value = node as RJSFSchema;
    if (!value.type || Array.isArray(value.type) || value.$ref || value.patternProperties || value.propertyNames) return true;
    if (value.type === 'object') return Object.values(value.properties ?? {}).some(needsJson)
      || typeof value.additionalProperties === 'object';
    if (value.type === 'array') return needsJson(value.items);
    return value.type === 'null';
  }
  return needsJson(schema) ? '此结构含可空类型、引用或复杂字段，请使用 JSON 参数保留完整结构。' : null;
}

export function ToolInputForm({schema, disabled, onTest}: {
  schema:RJSFSchema; disabled:boolean; onTest:(inputs:Record<string, unknown>) => void;
}) {
  const [inputs, setInputs] = useState<Record<string, unknown>>({});
  const [raw,setRaw] = useState('{}');
  const [jsonMode,setJsonMode] = useState(false);
  const [error,setError] = useState<string | null>(null);
  let reason = advancedReason(schema);
  if (!reason) {
    const validation=schemaValidatorFor(schema).rawValidation<ErrorObject>(schema,inputs);
    if (validation.validationError) reason='此 schema 无法在当前表单校验，使用 JSON 参数并由后端诊断。';
    else if (validation.errors?.some(error => ['type','enum','const'].includes(error.keyword)))
      reason='原输入与当前类型、枚举或常量不匹配；保留原输入，使用 JSON 参数并查看后端诊断。';
  }
  const advanced = jsonMode || Boolean(reason);
  const actions = <div className="tool-input-actions"><span>使用已保存的配置</span><Button size="sm" type="submit" aria-label="测试已保存工具" disabled={disabled || Boolean(error)}><Play size={14}/>执行测试</Button></div>;
  return <div className="tool-input-editor">
    <div className="tool-editor-modes" role="group" aria-label="测试参数模式">
      <Button size="sm" variant="outline" disabled={disabled || Boolean(error) || Boolean(reason)} aria-pressed={!advanced} onClick={() => setJsonMode(false)}>参数表单</Button>
      <Button size="sm" variant="outline" disabled={disabled || Boolean(error)} aria-pressed={advanced} onClick={() => setJsonMode(true)}>JSON 参数</Button>
    </div>
    {reason && <p className="tool-muted">{reason}</p>}
    {advanced ? <form className="tool-input-form" onSubmit={event => {event.preventDefault(); if (!disabled && !error) onTest(inputs);}}>
      <label htmlFor="tool-input-json">测试参数 JSON</label>
      <Textarea id="tool-input-json" rows={9} value={raw} disabled={disabled} aria-invalid={Boolean(error)} onChange={event => {
        const text=event.target.value; setRaw(text);
        const result=parseJson(text);
        if (result.error) setError(result.error);
        else if (!result.value || typeof result.value !== 'object' || Array.isArray(result.value)) setError('测试参数 JSON 必须是对象。');
        else {setError(null);setInputs(result.value as Record<string,unknown>);}
      }}/>
      {error && <p role="alert">{error}</p>}{actions}
    </form> : <SchemaForm className="tool-input-form" schema={schema} formData={inputs} disabled={disabled}
      omitExtraData={false} liveOmit={false} idPrefix="tool-input" onChange={event => {
        const next=event.formData ?? {};setInputs(next);
        if (hasNonFiniteNumber(next)) {setError('数字超出有限 JSON 数值范围，请修正原输入。');return;}
        setError(null);setRaw(JSON.stringify(next,null,2));
      }} onSubmit={event => {
        if (!error && !hasNonFiniteNumber(event.formData)) onTest(event.formData ?? {});
      }}>
      {error && <p role="alert">{error}</p>}
    {!Object.keys(schema.properties ?? {}).length && <div className="tool-empty-input"><p>{Object.keys(inputs).length ? '保留的实际输入为' : '无参数，实际输入为'}</p><pre aria-label="实际测试参数">{JSON.stringify(inputs,null,2)}</pre></div>}
      {actions}
    </SchemaForm>}
  </div>;
}
