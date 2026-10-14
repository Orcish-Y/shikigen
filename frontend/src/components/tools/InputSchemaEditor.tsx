import { useState } from 'react';
import type { FieldProps, RJSFSchema } from '@rjsf/utils';
import { Button } from '../ui/button';
import { Input } from '../ui/input';
import { JsonEditor } from './JsonEditor';

const locations = ['path','query','headers'] as const;
const primitiveTypes = ['string','integer','number','boolean'];
function objectSchema(value:unknown):value is RJSFSchema {
  return Boolean(value && typeof value === 'object' && !Array.isArray(value));
}
function editableField(value:unknown):value is RJSFSchema {
  return objectSchema(value) && typeof value.type === 'string' && primitiveTypes.includes(value.type)
    && !value.$ref && !value.anyOf && !value.oneOf && !value.allOf;
}

export function InputSchemaEditor({formData,onChange,fieldPathId,schema,disabled,readonly}:FieldProps) {
  const [advanced,setAdvanced] = useState(false);
  const [location,setLocation] = useState<(typeof locations)[number]>('query');
  const [newName,setNewName] = useState('');
  const [addError,setAddError] = useState<string | null>(null);
  const locked=disabled || readonly;
  const valid=objectSchema(formData) && formData.type === 'object' && !formData.$ref;
  const root=valid ? formData as RJSFSchema : null;
  const properties=root?.properties ?? {};
  const complex=Object.entries(properties).flatMap(([group,node]) => {
    if (!locations.includes(group as (typeof locations)[number]) || !objectSchema(node) || node.type !== 'object' || node.$ref) return [group];
    return Object.entries(node.properties ?? {}).filter(([,field]) => !editableField(field)).map(([name]) => `${group}.${name}`);
  });
  function change(group:string,name:string,edit:(node:RJSFSchema,group:RJSFSchema) => void) {
    if (!root) return;
    const next=structuredClone(root);
    const container=next.properties![group] as RJSFSchema;
    edit(container.properties![name] as RJSFSchema,container);
    onChange(next,fieldPathId.path);
  }
  return <div className="input-schema-editor">
    <div className="tool-editor-modes" role="group" aria-label="输入结构编辑模式">
      <Button type="button" size="sm" variant="outline" disabled={locked || !valid} aria-pressed={!advanced && valid} onClick={() => setAdvanced(false)}>参数表格</Button>
      <Button type="button" size="sm" variant="outline" disabled={locked} aria-pressed={advanced || !valid} onClick={() => setAdvanced(true)}>高级输入 JSON</Button>
    </div>
    {complex.length > 0 && <p className="tool-muted">复杂结构 {complex.join('、')} 使用高级 JSON 编辑，保留完整约束。</p>}
    {advanced || !root ? <JsonEditor id={fieldPathId.$id} label={schema.title ?? '输入结构'} value={formData} disabled={locked}
      onChange={value => onChange(value,fieldPathId.path)}/> : <>
      <div className="tool-parameter-table-wrap"><table className="tool-parameter-table"><caption>输入参数；类型和必填性只保存在 input_schema</caption>
        <thead><tr><th>位置／名称</th><th>类型</th><th>必填</th><th>说明</th><th>操作</th></tr></thead>
        <tbody>{locations.flatMap(group => {
          const container=properties[group];
          if (!objectSchema(container) || container.$ref) return [];
          return Object.entries(container.properties ?? {}).filter(([,node]) => editableField(node)).map(([name,node]) => {
            const field=node as RJSFSchema;
            const canChangeType=Object.keys(field).every(key => ['type','title','description','examples','example'].includes(key));
            return <tr key={`${group}.${name}`}><th scope="row"><code>{group}.{name}</code></th><td>
              <select className="tool-select" aria-label={`${group}.${name} 类型`} value={String(field.type)} disabled={locked || !canChangeType}
                onChange={event => change(group,name,node => {node.type=event.target.value as RJSFSchema['type'];})}>
                {primitiveTypes.map(type => <option key={type}>{type}</option>)}
              </select></td><td><input type="checkbox" aria-label={`${group}.${name} 必填`} disabled={locked} checked={container.required?.includes(name) ?? false}
                onChange={event => change(group,name,(_,parent) => {parent.required=event.target.checked ? [...(parent.required ?? []).filter(item => item !== name),name] : (parent.required ?? []).filter(item => item !== name);})}/></td>
              <td><Input aria-label={`${group}.${name} 说明`} value={field.description ?? ''} disabled={locked} onChange={event => change(group,name,node => {node.description=event.target.value;})}/></td>
              <td><Button type="button" size="sm" variant="outline" disabled={locked} aria-label={`删除 ${group}.${name}`} onClick={() => {
                const next=structuredClone(root); const parent=next.properties![group] as RJSFSchema;
                delete parent.properties![name];parent.required=(parent.required ?? []).filter(item => item !== name);
                onChange(next,fieldPathId.path);
              }}>删除</Button></td></tr>;
          });
        })}</tbody></table></div>
      {locations.filter(group => objectSchema(properties[group])).map(group => <label key={group} className="tool-group-required">
        <input type="checkbox" disabled={locked} checked={root.required?.includes(group) ?? false} onChange={event => {
          const next=structuredClone(root);next.required=event.target.checked ? [...(next.required ?? []).filter(item => item !== group),group] : (next.required ?? []).filter(item => item !== group);
          onChange(next,fieldPathId.path);
        }}/>{group} 分组必填</label>)}
      <div className="tool-add-parameter">
        <select aria-label="新参数位置" className="tool-select" disabled={locked} value={location} onChange={event => setLocation(event.target.value as typeof location)}>
          {locations.map(group => <option key={group}>{group}</option>)}
        </select>
        <Input aria-label="新参数名称" placeholder="参数名称" value={newName} disabled={locked} onChange={event => {setNewName(event.target.value);setAddError(null);}}/>
        <Button type="button" size="sm" variant="outline" disabled={locked || !newName.trim()} onClick={() => {
          const name=newName.trim();const current=properties[location];
          if (current && (!objectSchema(current) || current.type !== 'object' || current.$ref)) {setAddError('此分组为复杂结构，请使用高级 JSON。');return;}
          if (objectSchema(current) && Object.hasOwn(current.properties ?? {},name)) {setAddError('此分组已存在同名参数。');return;}
          const next=structuredClone(root);
          const parent=structuredClone(current ?? {type:'object',properties:{},additionalProperties:false}) as RJSFSchema;
          parent.properties={...parent.properties,[name]:{type:'string'}};
          if (location === 'path') {parent.required=[...(parent.required ?? []),name];next.required=[...new Set([...(next.required ?? []),'path'])];}
          next.properties={...next.properties,[location]:parent};onChange(next,fieldPathId.path);setNewName('');
        }}>添加参数</Button>
      </div>{addError && <p role="alert">{addError}</p>}
      <p className="tool-muted">已有约束保持原样；数组、嵌套 body、引用及可空类型在高级 JSON 中编辑。新字段自动补齐同名映射，目标名和序列化可在请求映射中修改。</p>
    </>}
  </div>;
}
