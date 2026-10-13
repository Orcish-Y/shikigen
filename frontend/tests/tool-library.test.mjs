import assert from 'node:assert/strict';
import test from 'node:test';
import {suggestToolName} from '../src/tool-library.ts';

test('调用名称建议在前端处理来源字符、空名称、数字开头及已占用名称', () => {
  assert.equal(suggestToolName('读取天气', []), 'tool');
  assert.equal(suggestToolName('', ['tool', 'tool_2']), 'tool_3');
  assert.equal(suggestToolName('123 weather', []), 'tool_123_weather');
  assert.equal(suggestToolName(' read / status ', ['read_status', 'read_status_2']), 'read_status_3');
  assert.equal(suggestToolName('add', ['add']), 'add_2');
  const longName = suggestToolName('9'.repeat(100), ['tool_' + '9'.repeat(50)]);
  assert.match(longName, /^[A-Za-z_][A-Za-z0-9_]*$/);
  assert.ok(longName.length <= 64);
});
