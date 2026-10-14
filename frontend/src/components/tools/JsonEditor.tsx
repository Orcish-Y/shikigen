import { useEffect, useRef, useState } from 'react';
import { Textarea } from '../ui/textarea';

export function hasNonFiniteNumber(value:unknown):boolean {
  if (typeof value === 'number') return !Number.isFinite(value);
  return value !== null && typeof value === 'object' && Object.values(value).some(hasNonFiniteNumber);
}

export function parseJson(text: string): {value?: unknown; error?: string} {
  try { return {value:JSON.parse(text,(_key,value:unknown) => {
    if (typeof value === 'number' && !Number.isFinite(value)) throw new Error('数字超出有限 JSON 数值范围。');
    return value;
  })}; }
  catch (error) { return {error:`JSON 无效：${error instanceof Error ? error.message : String(error)}`}; }
}

function serialize(value:unknown,emptyIsNull:boolean) {
  return typeof value === 'string' ? value : emptyIsNull && value == null ? '' : JSON.stringify(value ?? null,null,2);
}
export function JsonEditor({id,label,value,disabled,onChange,emptyIsNull=false}: {
  id:string; label:string; value:unknown; disabled?:boolean;
  onChange:(value:unknown) => void; emptyIsNull?:boolean;
}) {
  const [text,setText] = useState(() => serialize(value,emptyIsNull));
  const emitted = useRef(value);
  useEffect(() => {
    if (value !== emitted.current) {setText(serialize(value,emptyIsNull)); emitted.current=value;}
  }, [value,emptyIsNull]);
  const parsed = emptyIsNull && text.trim() === '' ? {value:null} : parseJson(text);
  return <div className="schema-editor">
    <label htmlFor={id}>{label}</label>
    <Textarea id={id} rows={7} value={text} disabled={disabled} aria-invalid={Boolean(parsed.error)}
      placeholder={emptyIsNull ? '未声明输出结构' : undefined} onChange={event => {
        const next = event.target.value;
        setText(next);
        const result = emptyIsNull && next.trim() === '' ? {value:null} : parseJson(next);
        emitted.current=result.error ? next : result.value;
        onChange(emitted.current);
      }}/>
    {parsed.error && <p role="alert">{parsed.error}</p>}
    {emptyIsNull && parsed.value === null && <p className="tool-muted">未声明输出结构；实际响应不按它校验或转换。</p>}
  </div>;
}
