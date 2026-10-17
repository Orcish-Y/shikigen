import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import {analyzePythonSource} from '../src/python-source.ts';
import {editTool, toolDraftFingerprint} from '../src/tool-library.ts';

const cases=JSON.parse(readFileSync(new URL('../../tests/fixtures/python_source_cases.json',import.meta.url),'utf8'));
for (const sample of cases) test(`Python 本地分析：${sample.id}`, () => {
  const result=analyzePythonSource(sample.source);
  assert.equal(result.source,sample.source);
  if (sample.local_error) {
    assert.equal(result.input_schema,null);
    assert.deepEqual(result.parameters,[]);
    assert.ok(result.diagnostics.some(item => item.code === sample.local_error));
    assert.equal(result.canAskBackend,Boolean(sample.fallback));
    for (const item of result.diagnostics) {
      assert.ok(item.from >= 0 && item.to >= item.from && item.to <= sample.source.length);
    }
  } else {
    assert.deepEqual(result.diagnostics,[]);
    assert.deepEqual(result.parameters.map(({name,type,required,default_expression}) =>
      default_expression === undefined ? [name,type,required] : [name,type,required,default_expression]),sample.parameters);
    assert.deepEqual(result.input_schema,{
      type:'object',properties:Object.fromEntries(sample.parameters.map(([name,type]) => [name,{type}])),
      required:sample.parameters.filter(([, ,required]) => required).map(([name]) => name),additionalProperties:false,
    });
  }
});

test('分析整个模块，源码和默认表达式始终作为数据，派生结构不进入草稿', () => {
  const source=`${'value = 1\n'.repeat(500)}def main(count: int = __import__('os').system('echo side_effect')): return count\n`;
  const result=analyzePythonSource(source);
  assert.ok(result.input_schema);
  assert.equal(result.parameters[0].default_expression,"__import__('os').system('echo side_effect')");
  const saved={id:'python',kind:'python',created_at:'now',updated_at:'now',code_path:'tools/code.py',source,
    input_schema:{type:'object',properties:{count:{type:'integer',default:9007199254740993}}},enabled:true};
  const draft=editTool(saved);
  const fingerprint=toolDraftFingerprint(draft);
  analyzePythonSource(draft.source);
  assert.equal(toolDraftFingerprint(draft),fingerprint);
  assert.equal(Object.hasOwn(draft,'input_schema'),false);
  assert.equal(Object.hasOwn(draft,'code_path'),false);
  assert.notEqual(toolDraftFingerprint({...draft,source:source+'\n'}),fingerprint);
});

test('空源码明确报错，不保留上次分析结果，特殊参数名保持普通属性', () => {
  assert.equal(analyzePythonSource(' \n').diagnostics[0].code,'python_source_empty');
  const valid=analyzePythonSource('def main(__proto__: int): return __proto__\n');
  assert.equal(Object.hasOwn(valid.input_schema.properties,'__proto__'),true);
  assert.deepEqual(valid.input_schema.required,['__proto__']);
  const invalid=analyzePythonSource('def main(:');
  assert.equal(invalid.input_schema,null);
  assert.deepEqual(invalid.parameters,[]);
});
