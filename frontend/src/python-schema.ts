import type {RJSFSchema} from '@rjsf/utils';
import type {PythonSourceAnalysis} from './python-source';
import {schemaValidatorFor} from './schema-validation';

export function isSchema(value:unknown):value is RJSFSchema {
  return Boolean(value && typeof value === 'object' && !Array.isArray(value));
}
const types=(node:RJSFSchema):string[] => (Array.isArray(node.type) ? node.type : node.type ? [node.type] : []).slice().sort();
const sameTypes=(left:RJSFSchema,right:RJSFSchema) => JSON.stringify(types(left)) === JSON.stringify(types(right));
const annotations=new Set(['title','description','default','examples','example','format','readOnly','writeOnly','deprecated','$comment']);
const supported=new Set([...annotations,'$schema','$ref','$defs','definitions','type','enum','const','properties','required','additionalProperties',
  'patternProperties','propertyNames','minProperties','maxProperties','items','minItems','maxItems','uniqueItems','minimum','maximum',
  'exclusiveMinimum','exclusiveMaximum','multipleOf','minLength','maxLength','pattern']);

export function resolvePythonSchemaReference(root:RJSFSchema,node:RJSFSchema,ancestors=new Set<unknown>()):RJSFSchema | null {
  if (!node.$ref) return node;
  if (!node.$ref.startsWith('#/') || ancestors.has(node)) return null;
  ancestors.add(node);
  let target:unknown=root;
  for (const segment of node.$ref.slice(2).split('/').map(item => item.replace(/~1/g,'/').replace(/~0/g,'~')))
    target=isSchema(target) && Object.hasOwn(target,segment) ? target[segment] : undefined;
  return isSchema(target) ? resolvePythonSchemaReference(root,target,ancestors) : null;
}

function fieldContractErrors(root:RJSFSchema,candidate:unknown,constraint:RJSFSchema,path:string,allowOpen=false,ancestors=new Set<unknown>()):string[] {
  if (typeof candidate === 'boolean' && allowOpen && !Object.keys(constraint).length) return [];
  const field=isSchema(candidate) ? resolvePythonSchemaReference(root,candidate) : null;
  if (!field) return [`${path}：请补齐类型或明确开放容器`];
  if (ancestors.has(field)) return [`${path}：不支持循环 schema 引用`];
  ancestors=new Set([...ancestors,field]);
  const errors:string[]=[];
  const reject=(message:string) => errors.push(`${path}：${message}`);
  const actual=types(field), expected=types(constraint);
  const unknown=!expected.length || expected.join() === 'null' && Array.isArray(constraint.type);
  if (!actual.length) return [`${path}：类型待补`];
  if (unknown) {
    if (actual.filter(type => type !== 'null').length !== 1 || actual.includes('null') !== expected.includes('null'))
      reject('请选择一个 JSON 类型；允许 null 须与源码注解一致');
  } else if (!sameTypes(field,constraint)) reject('不能改写源码确定的类型或 null 许可');
  function child(candidate:unknown,constraint:RJSFSchema,suffix:string) {
    errors.push(...fieldContractErrors(root,candidate,constraint,`${path}/${suffix}`,true,ancestors));
  }
  if (actual.includes('array')) {
    if (field.items === undefined) reject('数组元素待补，或明确设置 items: true 开放');
    else child(field.items,isSchema(constraint.items) ? constraint.items : {},'items');
  }
  if (actual.includes('object')) {
    const childConstraint=isSchema(constraint.additionalProperties) ? constraint.additionalProperties : {};
    for (const [name,node] of Object.entries(field.properties ?? {})) child(node,childConstraint,name);
    for (const [name,node] of Object.entries(field.patternProperties ?? {})) child(node,childConstraint,`patternProperties/${name}`);
    if (field.additionalProperties === undefined) reject('对象结构待补，请声明 additionalProperties');
    else if (field.additionalProperties !== false) child(field.additionalProperties,childConstraint,'additionalProperties');
  }
  return errors;
}

/** Check the editable schema against this source, independently of JSON syntax. */
export function pythonSchemaErrors(analysis:PythonSourceAnalysis, value:unknown):string[] {
  if (!analysis.input_schema) return [];
  if (!isSchema(value)) return ['输入结构必须是 JSON Schema 对象'];
  const errors:string[]=[];
  const reject=(path:string,message:string) => errors.push(`${path}：${message}`);
  const dialect=value.$schema ?? 'http://json-schema.org/draft-07/schema#';
  if (!['http://json-schema.org/draft-07/schema#','https://json-schema.org/draft-07/schema#','https://json-schema.org/draft/2020-12/schema'].includes(dialect))
    reject('input_schema','不支持此 JSON Schema 方言');
  function validateNode(node:unknown,path:string,ancestors=new Set<unknown>()) {
    if (!isSchema(node)) return;
    if (ancestors.has(node)) {reject(path,'不支持循环 schema 引用');return;}
    ancestors=new Set([...ancestors,node]);
    const unknown=Object.keys(node).filter(key => !supported.has(key));
    if (unknown.length) reject(path,`不支持的输入 schema 约束：${unknown.join('、')}`);
    if (node !== value && node.$schema) reject(path,'不支持嵌套 schema 方言');
    if (types(node).filter(type => type !== 'null').length > 1) reject(path,'仅支持单一类型加可选 null');
    if (Array.isArray(node.items)) reject(path,'不支持 tuple 数组结构');
    if (node.$ref) {
      const target=resolvePythonSchemaReference(value as RJSFSchema,node);
      if (!target) reject(path,'引用无效或循环');
      else validateNode(target,`${path}/$ref`,ancestors);
      if (dialect !== 'https://json-schema.org/draft/2020-12/schema' && Object.keys(node).some(key => key !== '$ref' && !annotations.has(key)))
        reject(path,'draft-07 引用旁的约束会被忽略，请编辑引用目标');
    }
    for (const key of ['properties','patternProperties','definitions','$defs'])
      if (isSchema(node[key])) for (const [name,child] of Object.entries(node[key] as object)) validateNode(child,`${path}/${key}/${name}`,ancestors);
    for (const key of ['items','additionalProperties','propertyNames']) validateNode(node[key],`${path}/${key}`,ancestors);
  }
  validateNode(value,'input_schema');
  const check=(candidate:unknown,constraint:RJSFSchema,path:string,allowOpen=false) => errors.push(...fieldContractErrors(value,candidate,constraint,path,allowOpen));
  const properties=value.properties ?? {}, inferred=analysis.input_schema.properties ?? {};
  const required=value.required ?? [];
  if (value.type !== 'object' || value.$ref || value.patternProperties) reject('input_schema','顶层参数须直接声明为 object');
  for (const parameter of analysis.parameters) {
    if (!Object.hasOwn(properties,parameter.name)) reject(parameter.name,'源码参数不能删除或改名');
    else check(properties[parameter.name],parameter.schema,parameter.name);
    if (required.includes(parameter.name) !== parameter.required) reject(parameter.name,'不能改写源码确定的必填性');
  }
  if (required.some(name => !Object.hasOwn(properties,name))) reject('input_schema','必填字段须在 properties 中声明');
  const extras=Object.entries(properties).filter(([name]) => !Object.hasOwn(inferred,name));
  if (analysis.extra_schema === null) {
    if (extras.length || value.additionalProperties !== false) reject('input_schema','main 未声明 **kwargs，不能新增参数或允许附加属性');
  } else {
    extras.forEach(([name,child]) => check(child,analysis.extra_schema!,name,true));
    if (value.additionalProperties === undefined) reject('**kwargs','请声明业务字段或明确允许附加属性');
    else if (value.additionalProperties !== false) check(value.additionalProperties,analysis.extra_schema,'**kwargs',true);
  }
  return errors;
}

export interface PythonSchemaChange {name:string; message:string; previous?:unknown; review:boolean}

/** Preserve only supplements compatible with the new source. Never guess renames. */
export function syncPythonInputSchema(previous:PythonSourceAnalysis, current:PythonSourceAnalysis, value:unknown):{schema:unknown;changes:PythonSchemaChange[]} {
  if (!current.input_schema || !previous.input_schema) return {schema:value,changes:[]};
  if (!isSchema(value) || schemaValidatorFor(value).rawValidation(value,{}).validationError)
    return {schema:value,changes:syncPythonInputSchema(previous,current,previous.input_schema).changes};
  const schema=structuredClone(value), changes:PythonSchemaChange[]=[];
  const before=previous.input_schema.properties ?? {}, after=current.input_schema.properties ?? {};
  const fields=value.properties ?? {};
  function merge(oldConstraint:RJSFSchema,newConstraint:RJSFSchema,candidate:unknown,path:string):RJSFSchema | boolean {
    if (typeof candidate === 'boolean' && !Object.keys(newConstraint).length) return candidate;
    const oldField=isSchema(candidate) ? candidate : {};
    if (oldField.$ref) {
      if (!fieldContractErrors(value as RJSFSchema,candidate,newConstraint,path).length) return structuredClone(oldField);
      changes.push({name:path,message:'引用字段类型变化，请按当前源码重新补齐；原引用保留在变更记录',previous:candidate,review:true});
      return structuredClone(newConstraint);
    }
    const known=types(newConstraint).filter(type => type !== 'null').length > 0;
    const oldKnown=types(oldConstraint).filter(type => type !== 'null').length > 0;
    const incompatible=(known && (oldKnown ? !sameTypes(oldConstraint,newConstraint) : oldField.type && !sameTypes(oldField,newConstraint)))
      || types(oldConstraint).includes('null') !== types(newConstraint).includes('null');
    if (incompatible) {
      changes.push({name:path,message:'类型变化，原补充已保留在变更记录，请按当前源码重新补齐',previous:candidate,review:true});
      return structuredClone(newConstraint);
    }
    const next={...oldField,...newConstraint};
    for (const key of ['items','additionalProperties'] as const) {
      const child=newConstraint[key];
      if (isSchema(child)) next[key]=merge(isSchema(oldConstraint[key]) ? oldConstraint[key] : {},child,oldField[key],`${path}/${key}`);
    }
    // Constraints on named dictionary entries must also agree with its value annotation.
    if (isSchema(newConstraint.additionalProperties)) {
      for (const key of ['properties','patternProperties'] as const) if (oldField[key])
        next[key]=Object.fromEntries(Object.entries(oldField[key]!).map(([name,node]) => [name,merge(
          isSchema(oldConstraint.additionalProperties) ? oldConstraint.additionalProperties : {},
          newConstraint.additionalProperties as RJSFSchema,node,`${path}/${name}`)]));
      if (oldField.additionalProperties === false) next.additionalProperties=false;
    }
    return next;
  }
  schema.properties=Object.fromEntries(Object.entries(after).map(([name,node]) => {
    if (!Object.hasOwn(before,name)) {
      changes.push({name,message:'新增参数',review:false});
      return [name,Object.hasOwn(fields,name) ? merge({},node as RJSFSchema,fields[name],name) : structuredClone(node)];
    }
    const wasRequired=previous.input_schema!.required?.includes(name) ?? false;
    const required=current.input_schema!.required?.includes(name) ?? false;
    if (wasRequired !== required) changes.push({name,message:`必填变化：${required ? '必填' : '可省略'}`,review:true});
    return [name,merge(before[name] as RJSFSchema,node as RJSFSchema,fields[name],name)];
  }));
  for (const name of Object.keys(before)) if (!Object.hasOwn(after,name))
    changes.push({name,message:'删除参数；改名按删除和新增处理',previous:fields[name],review:true});
  const oldExtras=Object.entries(fields).filter(([name]) => !Object.hasOwn(before,name));
  if (current.extra_schema !== null) {
    for (const [name,node] of oldExtras) if (!Object.hasOwn(after,name)) schema.properties={...schema.properties,[name]:merge(previous.extra_schema ?? {},current.extra_schema,node,name)};
    if (previous.extra_schema === null) {
      if (Object.keys(current.extra_schema).length) schema.additionalProperties=current.extra_schema;
      else delete schema.additionalProperties;
      changes.push({name:'**kwargs',message:'新增额外关键字参数，请声明业务字段或开放附加属性',review:false});
    } else if (schema.additionalProperties !== undefined && schema.additionalProperties !== false)
      schema.additionalProperties=merge(previous.extra_schema,current.extra_schema,schema.additionalProperties,'**kwargs');
  } else {
    schema.additionalProperties=false;
    if (previous.extra_schema !== null) changes.push({name:'**kwargs',message:'删除额外关键字参数',previous:oldExtras,review:true});
  }
  schema.required=[...(current.input_schema.required ?? []),...(current.extra_schema === null ? [] : (value.required ?? []).filter(name => !Object.hasOwn(before,name) && !Object.hasOwn(after,name)))];
  return {schema,changes};
}
