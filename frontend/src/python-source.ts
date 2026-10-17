import {parser} from '@lezer/python';
import type {SyntaxNode} from '@lezer/common';
import type {RJSFSchema} from '@rjsf/utils';

export interface PythonDiagnostic {
  from:number;
  to:number;
  severity:'error' | 'warning';
  code:string;
  message:string;
}

export interface PythonParameter {
  name:string;
  type:RJSFSchema['type'] | null;
  schema:RJSFSchema;
  type_expression:string;
  required:boolean;
  default_expression?:string;
  from:number;
  to:number;
}

export interface PythonSourceAnalysis {
  source:string;
  input_schema:RJSFSchema | null;
  parameters:PythonParameter[];
  diagnostics:PythonDiagnostic[];
  canAskBackend:boolean;
  extra_schema:RJSFSchema | null;
  backendValidationRequested:boolean;
}

const annotationTypes:Record<string, RJSFSchema['type']> = {str:'string', int:'integer', float:'number', bool:'boolean', list:'array', List:'array', dict:'object', Dict:'object'};

function children(node:SyntaxNode):SyntaxNode[] {
  const result:SyntaxNode[] = [];
  for (let child=node.firstChild;child;child=child.nextSibling) result.push(child);
  return result;
}

/** Analyze the whole module. Never execute source, annotations, or defaults. */
export function analyzePythonSource(source:string):PythonSourceAnalysis {
  const diagnostics:PythonDiagnostic[] = [];
  const result:PythonSourceAnalysis = {source, input_schema:null, parameters:[], diagnostics, canAskBackend:false, extra_schema:null, backendValidationRequested:false};
  const text = (node:SyntaxNode) => source.slice(node.from, node.to);
  function diagnose(node:SyntaxNode | null, code:string, message:string, severity:'error' | 'warning' = 'error') {
    diagnostics.push({from:node?.from ?? 0, to:node?.to ?? source.length, code, message, severity});
  }
  function annotationSchema(node:SyntaxNode | undefined, depth=0):RJSFSchema {
    if (!node || depth > 30) return {};
    const expression=text(node);
    if (node.name === 'String') {
      const quoted=/^(?:[rRuU])?(?:'([^'\\\n]*)'|"([^"\\\n]*)")$/.exec(expression);
      if (!quoted) {
        diagnose(node,'python_annotation','本地无法解析转义注解，可交给后端校验','warning');
        result.canAskBackend=true;
        return {};
      }
      const content=quoted[1] ?? quoted[2];
      const quotedSource=`def main(value: ${content}): pass`;
      const annotation=parser.parse(quotedSource).topNode.getChild('FunctionDefinition')?.getChild('ParamList')?.getChild('TypeDef');
      // Analyze quoted expressions in their own source coordinate system.
      const nested=analyzePythonSource(quotedSource);
      return annotation && nested.parameters[0]?.schema || {};
    }
    if (expression === 'None') return {type:'null'};
    const name=expression.replace(/^typing\./,'').normalize('NFKC');
    if (Object.hasOwn(annotationTypes,name)) return {type:annotationTypes[name]};
    const parts=children(node);
    let members:RJSFSchema[] | null=null;
    if (node.name === 'BinaryExpression' && parts[1] && text(parts[1]) === '|')
      members=[annotationSchema(parts[0],depth+1),annotationSchema(parts[2],depth+1)];
    if (node.name === 'MemberExpression' && parts.some(part => part.name === '[')) {
      const base=text(parts[0]).replace(/^typing\./,'');
      const args=parts.slice(2,-1).filter(part => part.name !== ',');
      if (['list','List'].includes(base) && args.length === 1) return {type:'array',items:annotationSchema(args[0],depth+1)};
      if (['dict','Dict'].includes(base) && args.length === 2) {
        if (annotationSchema(args[0],depth+1).type !== 'string') diagnose(node,'python_annotation','字典注解仅支持 dict[str, T]');
        return {type:'object',additionalProperties:annotationSchema(args[1],depth+1)};
      }
      if (base === 'Optional' && args.length === 1) members=[annotationSchema(args[0],depth+1),{type:'null'}];
      if (base === 'Union' && args.length === 2) members=args.map(arg => annotationSchema(arg,depth+1));
    }
    if (members) {
      const nonNull=members.filter(member => member.type !== 'null');
      if (nonNull.length === 1) return {...nonNull[0],type:[...new Set([...(Array.isArray(nonNull[0].type) ? nonNull[0].type : nonNull[0].type ? [nonNull[0].type] : []),'null' as const])]};
    }
    return {};
  }
  if (!source.trim()) {
    diagnose(null, 'python_source_empty', 'Python 源码不能为空');
    return result;
  }

  const tree = parser.parse(source);
  tree.iterate({enter(node) {
    if (node.type.isError && diagnostics.length < 20)
      diagnose(node.node, 'python_syntax', '此处源码不完整或超出本地语法支持范围', 'warning');
  }});
  if (diagnostics.length) {
    // A recovering editor grammar cannot distinguish every CPython syntax error
    // from valid syntax it does not support. Offer an explicit backend fallback.
    result.canAskBackend = true;
    return result;
  }

  const entries = children(tree.topNode).flatMap(node => {
    const definition = node.name === 'DecoratedStatement' ? node.getChild('FunctionDefinition') : node;
    const name = definition?.getChild('VariableName');
    return definition?.name === 'FunctionDefinition' && name && text(name).normalize('NFKC') === 'main'
      ? [{definition, decorated:node.name === 'DecoratedStatement'}] : [];
  });
  if (entries.length !== 1) {
    diagnose(entries[1]?.definition ?? tree.topNode, 'python_entry', '需要唯一的顶层同步函数 main');
    return result;
  }
  const {definition, decorated} = entries[0];
  if (decorated || definition.getChild('async')) {
    diagnose(definition, 'python_entry', 'main 不支持异步函数或装饰器');
    return result;
  }

  function findYield(node:SyntaxNode):SyntaxNode | null {
    if (['FunctionDefinition', 'LambdaExpression'].includes(node.name)) return null;
    if (node.name.startsWith('Yield')) return node;
    for (const child of children(node)) {
      const found = findYield(child);
      if (found) return found;
    }
    return null;
  }
  const body = definition.getChild('Body');
  const generator = body && findYield(body);
  if (generator) {
    diagnose(generator, 'python_entry', 'main 不支持生成器入口');
    return result;
  }

  const signature = definition.getChild('ParamList')!;
  const groups:SyntaxNode[][] = [[]];
  let consumed=signature.from;
  for (const part of children(signature)) {
    // Lezer does not retain the positional-only '/' as a named child.
    // Inspect gaps between immediate syntax nodes, never text inside defaults,
    // annotations or comments (which have their own ranges).
    const slash=source.slice(consumed,part.from).indexOf('/');
    if (slash >= 0) diagnostics.push({from:consumed+slash,to:consumed+slash+1,severity:'error',
      code:'python_signature',message:'当前不支持仅位置参数 /'});
    consumed=part.to;
    if (['(', ')', 'Comment'].includes(part.name)) continue;
    if (part.name === ',') groups.push([]);
    else groups.at(-1)!.push(part);
  }
  const parameters:PythonParameter[] = [];
  const names = new Set<string>();
  let hasDefault = false;
  let keywordOnly=false;
  let seenKwargs=false;
  for (const group of groups.filter(parts => parts.length)) {
    if (group[0].name === '*' && group.length === 1) {keywordOnly=true;continue;}
    const kwargs=group[0].name === '**';
    const parts=kwargs ? group.slice(1) : group;
    const nameNode=parts[0];
    const annotation=parts.find(part => part.name === 'TypeDef');
    const assignment=parts.findIndex(part => part.name === 'AssignOp');
    const defaultNode=assignment >= 0 ? parts[assignment+1] : undefined;
    if (nameNode?.name !== 'VariableName' || parts.length > 4 || seenKwargs
      || assignment >= 0 && !defaultNode) {
      diagnose(nameNode, 'python_signature', '不支持仅位置参数、*args 或此参数声明');
      continue;
    }
    const name = text(nameNode).normalize('NFKC');
    if (names.has(name)) diagnose(nameNode, 'python_signature', `参数 ${name} 重复声明`);
    names.add(name);
    const typeNode = annotation?.name === 'TypeDef' ? children(annotation).find(node => node.name !== ':') : undefined;
    const expression = typeNode ? text(typeNode) : '';
    const schema=annotationSchema(typeNode);
    const type=schema.type ?? null;
    if (kwargs) {result.extra_schema=schema;seenKwargs=true;continue;}
    if (!keywordOnly && hasDefault && !defaultNode) diagnose(nameNode, 'python_signature', '有默认值的参数后不能声明必填参数');
    if (defaultNode) hasDefault = true;
    parameters.push({name, type, schema, type_expression:expression, required:!defaultNode,
      ...(defaultNode ? {default_expression:text(defaultNode)} : {}), from:nameNode.from, to:nameNode.to});
  }
  if (diagnostics.length) {
    if (diagnostics.some(item => item.severity === 'error')) result.canAskBackend = false;
    return result;
  }
  result.parameters = parameters;
  result.input_schema = {
    type:'object',
    properties:Object.fromEntries(parameters.map(parameter => [parameter.name, parameter.schema])),
    required:parameters.filter(parameter => parameter.required).map(parameter => parameter.name),
    ...(result.extra_schema === null ? {additionalProperties:false} : Object.keys(result.extra_schema).length ? {additionalProperties:result.extra_schema} : {}),
  };
  return result;
}
