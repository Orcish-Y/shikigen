import type { FieldProps } from '@rjsf/utils';
import { Button } from '../ui/button';
import { Input } from '../ui/input';
import type { HttpAuthBinding } from '../../tool-library';

const authenticationOptions=<><option value="bearer">Bearer Token</option>
  <option value="api_key_header">API Key（请求头）</option><option value="api_key_query">API Key（查询参数）</option></>;
function authenticationMode(binding:HttpAuthBinding):string {
  return binding.kind === 'bearer' ? 'bearer' : binding.location === 'query' ? 'api_key_query' : 'api_key_header';
}

export function HttpAuthEditor({formData,fieldPathId,onChange,disabled,readonly}:FieldProps) {
  const bindings:HttpAuthBinding[]=Array.isArray(formData) ? formData : [];
  const locked=disabled || readonly;
  const change=(next:HttpAuthBinding[]) => onChange(next,fieldPathId.path);
  function makeBinding(mode:string, current?:HttpAuthBinding):HttpAuthBinding {
    let number=1;
    while (bindings.some(binding => binding.id === `auth_${number}`)) number++;
    return {id:current?.id ?? `auth_${number}`,kind:mode === 'bearer' ? 'bearer' : 'api_key',
      location:mode === 'api_key_query' ? 'query' : 'headers',
      name:mode === 'bearer' ? 'Authorization' : mode === 'api_key_query' ? 'api_key' : 'X-Api-Key',
      value:current?.value ?? ''};
  }
  const mode=bindings.length > 1 ? 'multiple' : bindings[0]
    ? authenticationMode(bindings[0]) : 'none';
  return <div className="tool-auth-editor">
    <label htmlFor={`${fieldPathId.$id}-mode`}>认证方式</label>
    <select id={`${fieldPathId.$id}-mode`} className="tool-select" value={mode} disabled={locked}
      onChange={event => change(event.target.value === 'none' ? [] : [makeBinding(event.target.value,bindings[0])])}>
      <option value="none">无认证</option>{authenticationOptions}
      {bindings.length > 1 && <option value="multiple" disabled>组合认证</option>}
    </select>
    {bindings.map((binding,index) => {
      const update=(next:HttpAuthBinding) => change(bindings.map((item,position) => position === index ? next : item));
      const suffix=index ? ` ${index+1}` : '';
      return <fieldset key={binding.id} className="tool-auth-binding" disabled={locked}>
        <legend>认证凭据 {index+1}</legend>
        {bindings.length > 1 && <><label htmlFor={`${fieldPathId.$id}-${index}-kind`}>凭据类型{suffix}</label>
          <select id={`${fieldPathId.$id}-${index}-kind`} className="tool-select" value={authenticationMode(binding)}
            onChange={event => update(makeBinding(event.target.value,binding))}>
            {authenticationOptions}
          </select></>}
        {binding.kind === 'api_key' && <><label htmlFor={`${fieldPathId.$id}-${index}-name`}>凭据参数名{suffix}</label>
          <Input id={`${fieldPathId.$id}-${index}-name`} value={binding.name} disabled={locked}
            onChange={event => update({...binding,name:event.target.value})}/></>}
        <label htmlFor={`${fieldPathId.$id}-${index}-secret`}>认证密钥{suffix}</label>
        <Input id={`${fieldPathId.$id}-${index}-secret`} type="password" autoComplete="new-password" spellCheck={false}
          disabled={locked} value={binding.value ?? ''} onChange={event => update({...binding,value:event.target.value})}/>
        {bindings.length > 1 && <Button type="button" size="sm" variant="outline" disabled={locked}
          onClick={() => change(bindings.filter((_item,position) => position !== index))}>移除凭据 {index+1}</Button>}
      </fieldset>;
    })}
    {bindings.length > 0 && <Button type="button" size="sm" variant="outline" disabled={locked}
      onClick={() => change([...bindings,makeBinding('api_key_header')])}>添加认证凭据</Button>}
    <p className="tool-muted">密钥独立于业务参数，直接保存到项目配置；重新读取会填入密码框，清空后保存即删除该值。</p>
  </div>;
}
