import type {RJSFSchema} from '@rjsf/utils';
import {schemaValidatorFor} from './schema-validation';
import {suggestToolName, type HttpAuthBinding, type HttpToolDraft} from './tool-library';

export interface OpenApiSecurityOption {id:string; label:string; auth:HttpAuthBinding[]; errors:string[]}

export interface OpenApiOperation {
  key:string; method:string; path:string; name_hint:string;
  servers:{url:string; description?:string; variables?:Record<string,unknown>}[];
  definition:HttpToolDraft; errors:string[]; warnings:string[]; configuration_errors:string[];
  security_options?:OpenApiSecurityOption[]; security_option?:string | null;
}
export interface OpenApiPreview {openapi:string; title:string; operations:OpenApiOperation[]}
export interface OpenApiSelection {operation_key:string; definition:HttpToolDraft; security_option?:string | null}

export function nameOpenApiOperations(preview:OpenApiPreview, occupied:Iterable<string>):OpenApiOperation[] {
  const names=new Set(occupied);
  return preview.operations.map(operation => {
    const name=suggestToolName(operation.name_hint,names);names.add(name);
    return {...operation,definition:{...operation.definition,name}};
  });
}

export function openApiConfigurationErrors(operation:OpenApiOperation,schema:RJSFSchema):string[] {
  const definition=operation.definition;
  const errors=[...operation.errors];
  if (operation.security_options) {
    const option=operation.security_options.find(item => item.id === operation.security_option);
    if (!option || option.errors.length) errors.push('security：请选择受支持的来源认证方案');
    else {
      const auth=Array.isArray(definition.auth) ? definition.auth : [];
      const target=(binding:HttpAuthBinding) => JSON.stringify([binding?.kind,binding?.location,
        binding?.location === 'headers' ? binding?.name?.toLowerCase() : binding?.name]);
      if (auth.length !== option.auth.length || option.auth.some(binding => !auth.some(actual => target(actual) === target(binding))))
        errors.push('auth：请补齐所选认证方案的全部绑定，或选择其他方案');
      auth.forEach((binding,index) => {if (typeof binding?.value !== 'string' || !binding.value.trim()) errors.push(`auth/${index}/value：请补齐 ${binding?.name ?? ''} 的认证值`);});
    }
  }
  const validation=schemaValidatorFor(schema).rawValidation(schema,definition);
  if (validation.validationError || validation.errors?.length) errors.push('请补齐有效的工具配置');
  if (typeof definition.display_name !== 'string' || !definition.display_name.trim()) errors.push('请补充页面名称');
  if (typeof definition.description !== 'string' || !definition.description.trim()) errors.push('请补充用途说明');
  if (!/^[A-Za-z_][A-Za-z0-9_]{0,63}$/.test(definition.name)) errors.push('请填写合法调用名称');
  try {
    const url=new URL(definition.url);
    const placeholders=[...definition.url.matchAll(/\{([^{}]+)\}/g)].map(match => match[1]);
    const pathNames=Array.isArray(definition.parameters) ? definition.parameters.filter(mapping => mapping?.location === 'path').map(mapping => mapping.name) : [];
    const serverVariables=operation.servers.flatMap(server => [...server.url.matchAll(/\{([^{}]+)\}/g)].map(match => match[1]));
    const pathPlaceholders=[...operation.path.matchAll(/\{([^{}]+)\}/g)].map(match => match[1]);
    if (!['http:','https:'].includes(url.protocol) || !url.hostname || url.username || url.password || url.hash
      || /\s/.test(definition.url) || placeholders.some(name => !pathNames.includes(name))
      || serverVariables.some(name => placeholders.filter(value => value === name).length > pathPlaceholders.filter(value => value === name).length)) throw new Error();
  } catch {errors.push('请补齐有效的绝对 HTTP(S) 地址及服务器变量');}
  return errors;
}
