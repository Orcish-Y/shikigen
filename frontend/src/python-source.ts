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
  type:'string' | 'integer' | 'number' | 'boolean';
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
}

const scalarTypes:Record<string, PythonParameter['type']> = {str:'string', int:'integer', float:'number', bool:'boolean'};

function children(node:SyntaxNode):SyntaxNode[] {
  const result:SyntaxNode[] = [];
  for (let child=node.firstChild;child;child=child.nextSibling) result.push(child);
  return result;
}

/** Analyze the whole module. Never execute source, annotations, or defaults. */
export function analyzePythonSource(source:string):PythonSourceAnalysis {
  const diagnostics:PythonDiagnostic[] = [];
  const result:PythonSourceAnalysis = {source, input_schema:null, parameters:[], diagnostics, canAskBackend:false};
  const text = (node:SyntaxNode) => source.slice(node.from, node.to);
  function diagnose(node:SyntaxNode | null, code:string, message:string, severity:'error' | 'warning' = 'error') {
    diagnostics.push({from:node?.from ?? 0, to:node?.to ?? source.length, code, message, severity});
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
  for (const group of groups.filter(parts => parts.length)) {
    const [nameNode, annotation, assignment, defaultNode] = group;
    if (nameNode.name !== 'VariableName' || group.length > 4
      || assignment && (assignment.name !== 'AssignOp' || !defaultNode)) {
      diagnose(nameNode, 'python_signature', '当前仅支持普通具名参数，不支持 /、*args、仅关键字参数或 **kwargs');
      continue;
    }
    const name = text(nameNode).normalize('NFKC');
    if (names.has(name)) diagnose(nameNode, 'python_signature', `参数 ${name} 重复声明`);
    names.add(name);
    const typeNode = annotation?.name === 'TypeDef' ? children(annotation).find(node => node.name !== ':') : undefined;
    const expression = typeNode ? text(typeNode) : '';
    // Simple string annotations are accepted without interpreting Python escapes.
    // More complex quoted annotations remain a backend decision.
    const quoted = /^(?:[rRuU])?(?:'([^'\\\n]*)'|"([^"\\\n]*)")$/.exec(expression);
    const typeName = typeNode?.name === 'VariableName' ? expression.normalize('NFKC') : quoted?.[1] ?? quoted?.[2];
    const type = typeName && Object.hasOwn(scalarTypes, typeName) ? scalarTypes[typeName] : undefined;
    if (!type) {
      const quotedUnknown = typeNode && ['String', 'ContinuedString'].includes(typeNode.name);
      diagnose(typeNode ?? nameNode, 'python_annotation', `参数 ${name} 的类型待补；当前支持 str、int、float、bool`, quotedUnknown ? 'warning' : 'error');
      if (quotedUnknown) result.canAskBackend = true;
      continue;
    }
    if (hasDefault && !defaultNode) diagnose(nameNode, 'python_signature', '有默认值的参数后不能声明必填参数');
    if (defaultNode) hasDefault = true;
    parameters.push({name, type, type_expression:expression, required:!defaultNode,
      ...(defaultNode ? {default_expression:text(defaultNode)} : {}), from:nameNode.from, to:nameNode.to});
  }
  if (diagnostics.length) {
    if (diagnostics.some(item => item.severity === 'error')) result.canAskBackend = false;
    return result;
  }
  result.parameters = parameters;
  result.input_schema = {
    type:'object',
    properties:Object.fromEntries(parameters.map(parameter => [parameter.name, {type:parameter.type}])),
    required:parameters.filter(parameter => parameter.required).map(parameter => parameter.name),
    additionalProperties:false,
  };
  return result;
}
