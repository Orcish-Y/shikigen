import {useState} from 'react';
import type {FieldProps, RJSFSchema} from '@rjsf/utils';
import {Button} from '../ui/button';
import {Input} from '../ui/input';
import {JsonEditor} from './JsonEditor';
import {isSchema, resolvePythonSchemaReference, type PythonSchemaChange} from '../../python-schema';
import type {PythonSourceAnalysis} from '../../python-source';

export function PythonParameters({formData,onChange,fieldPathId,registry,disabled,readonly}:FieldProps) {
  const [advanced,setAdvanced]=useState(false);
  const {pythonAnalysis:analysis,localPythonAnalysis:local,backendOnly,onBackendValidation,pythonChanges:changes,onConfirmPythonChanges}=registry.formContext as {
    pythonAnalysis:PythonSourceAnalysis; localPythonAnalysis:PythonSourceAnalysis;
    backendOnly:boolean; onBackendValidation:() => void; pythonChanges:PythonSchemaChange[]; onConfirmPythonChanges:() => void;
  };
  const locked=disabled || readonly;
  function edit(name:string,patch:Partial<RJSFSchema>) {
    if (!isSchema(formData)) return;
    const next=structuredClone(formData);
    next.properties={...next.properties,[name]:{...(isSchema(next.properties?.[name]) ? next.properties[name] : {}),...patch}};
    onChange(next,fieldPathId.path);
  }
  return <section aria-label="源码参数预览" className="tool-python-preview">
    <p className="tool-muted">名称、已识别类型和必填性来自 main。待补类型由你选择；容器内部结构和业务约束可在高级 JSON 中补充。默认值不注入实际测试输入。</p>
    {analysis.diagnostics.map((diagnostic,index) => <p role="alert" key={index}>
      第 {analysis.source.slice(0,diagnostic.from).split('\n').length} 行 · {diagnostic.code}：{diagnostic.message}
    </p>)}
    {changes.length > 0 && <div className="tool-python-changes" aria-label="源码变更">
      {changes.map((change,index) => <div key={index}><p><code>{change.name}</code> · {change.message}</p>
        {change.previous !== undefined && <details><summary>查看原补充</summary><pre>{JSON.stringify(change.previous,null,2)}</pre></details>}</div>)}
      {changes.some(change => change.review) && <Button type="button" size="sm" variant="outline" disabled={locked} onClick={onConfirmPythonChanges}>确认源码变更</Button>}
    </div>}
    {analysis.canAskBackend && !backendOnly && <><p className="tool-muted">本地无法确认这段源码。可以继续编辑，或交给后端校验；不会沿用旧参数结构。</p>
      <Button type="button" size="sm" variant="outline" disabled={locked} onClick={onBackendValidation}>交给后端校验</Button></>}
    {backendOnly && <p role="status">保存和测试将由后端校验当前源码。测试参数请使用 JSON 填写。</p>}
    {local.input_schema && !backendOnly && <>
      <div className="tool-editor-modes" role="group" aria-label="Python 输入结构编辑模式">
        <Button type="button" size="sm" variant="outline" disabled={locked || !isSchema(formData)} aria-pressed={!advanced} onClick={() => setAdvanced(false)}>参数表格</Button>
        <Button type="button" size="sm" variant="outline" disabled={locked} aria-pressed={advanced || !isSchema(formData)} onClick={() => setAdvanced(true)}>高级输入 JSON</Button>
      </div>
      {advanced || !isSchema(formData) ? <JsonEditor id={fieldPathId.$id} label="Python 输入结构 JSON" value={formData} disabled={locked}
        onChange={value => onChange(value,fieldPathId.path)}/> : <div className="tool-parameter-table-wrap"><table className="tool-parameter-table">
        <thead><tr><th>参数</th><th>类型</th><th>提供要求</th><th>函数默认值／补充</th></tr></thead>
        <tbody>{local.parameters.map(parameter => {
          const field=formData.properties?.[parameter.name];
          const resolved=isSchema(field) ? resolvePythonSchemaReference(formData,field) : null;
          const inferred=Array.isArray(parameter.type) ? parameter.type.filter(type => type !== 'null') : parameter.type ? [parameter.type] : [];
          const actual=inferred[0] ?? (resolved ? Array.isArray(resolved.type) ? resolved.type.find(type => type !== 'null') : resolved.type : '');
          return <tr key={parameter.name}><th scope="row"><code>{parameter.name}</code></th><td>
            <select className="tool-select" aria-label={`${parameter.name} 类型`} value={actual ?? ''} disabled={locked || inferred.length > 0 || Boolean(isSchema(field) && field.$ref)}
              onChange={event => edit(parameter.name,{type:parameter.type && Array.isArray(parameter.type) && parameter.type.includes('null')
                ? [event.target.value as 'string','null'] : event.target.value as RJSFSchema['type']})}>
              <option value="">待补类型</option>{['string','integer','number','boolean','object','array',...(parameter.type === 'null' ? ['null'] : [])].map(type => <option key={type}>{type}</option>)}
            </select>{Array.isArray(parameter.type) && parameter.type.includes('null') && <span>允许 null</span>}</td>
            <td>{parameter.required ? '必填' : '可省略'}</td><td><code>{parameter.default_expression ?? '无'}</code>
              <Input aria-label={`${parameter.name} 说明`} disabled={locked} value={isSchema(field) ? field.description ?? '' : ''} onChange={event => edit(parameter.name,{description:event.target.value})}/>
              {isSchema(field) && field.type === 'array' && !Object.hasOwn(parameter.schema,'items') && field.items === undefined
                && <Button type="button" size="sm" variant="outline" disabled={locked} onClick={() => edit(parameter.name,{items:true})}>开放 {parameter.name} 元素</Button>}
              {isSchema(field) && field.type === 'object' && !Object.hasOwn(parameter.schema,'additionalProperties') && field.additionalProperties === undefined
                && <Button type="button" size="sm" variant="outline" disabled={locked} onClick={() => edit(parameter.name,{additionalProperties:true})}>开放 {parameter.name} 属性</Button>}
            </td></tr>;
        })}</tbody></table></div>}
      {local.extra_schema !== null && <p className="tool-muted">main 接收 **kwargs。使用高级 JSON 声明额外业务字段及必填性，或显式设置 additionalProperties 允许附加属性。</p>}
      {local.parameters.length === 0 && local.extra_schema === null && <p>main 无参数，实际输入为 {'{}'}。</p>}
      <p className="tool-muted">自定义对象不会自动构造。保存和测试前，后端会按当前源码再次核对 schema。</p>
    </>}
  </section>;
}
