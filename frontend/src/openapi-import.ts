import type {RJSFSchema} from '@rjsf/utils';
import {schemaValidatorFor} from './schema-validation';
import {suggestToolName, type HttpToolDraft} from './tool-library';

export interface OpenApiOperation {
  key:string; method:string; path:string; name_hint:string;
  servers:{url:string; description?:string; variables?:Record<string,unknown>}[];
  definition:HttpToolDraft; errors:string[]; warnings:string[]; configuration_errors:string[];
}
export interface OpenApiPreview {openapi:string; title:string; operations:OpenApiOperation[]}
export interface OpenApiSelection {operation_key:string; definition:HttpToolDraft}

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
