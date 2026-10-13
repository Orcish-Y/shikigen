import { useState } from 'react';
import type { RJSFSchema } from '@rjsf/utils';
import { SchemaForm } from './SchemaForm';
import { Button } from '../ui/button';
import { Play } from '@phosphor-icons/react';

export function ToolInputForm({schema, disabled, onTest}: {
  schema:RJSFSchema; disabled:boolean; onTest:(inputs:Record<string, unknown>) => void;
}) {
  const [inputs, setInputs] = useState<Record<string, unknown>>({});
  return <SchemaForm className="tool-input-form" schema={schema} formData={inputs} disabled={disabled}
    idPrefix="tool-input" onChange={event => setInputs(event.formData ?? {})}
    onSubmit={event => onTest(event.formData ?? {})}>
    {!Object.keys(schema.properties ?? {}).length && <div className="tool-empty-input"><p>无参数，实际输入为</p><pre aria-label="实际测试参数">{'{}'}</pre></div>}
    <div className="tool-input-actions"><span>使用已保存的配置</span><Button size="sm" type="submit" aria-label="测试已保存工具" disabled={disabled}><Play size={14}/>执行测试</Button></div>
  </SchemaForm>;
}
