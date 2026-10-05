import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { MessageBody } from '../src/components/MessageBody.tsx';

const render = (role, content, extra = {}) => renderToStaticMarkup(React.createElement(MessageBody,
  {role, content, identity:'thread:run:message', onView:() => {}, ...extra}));

test('Agent 正文有 Markdown 层级，用户与工具保留原始空白和符号', () => {
  const raw = '  # 标题\n\n**原文**  \n';
  assert.match(render('assistant', raw), /<h1>标题<\/h1>/);
  for (const role of ['user', 'tool']) {
    const html = render(role, raw);
    assert.ok(html.includes(raw));
    assert.doesNotMatch(html, /<h1>|<strong>原文/);
  }
});

test('内容块保留原顺序，未知对象不提取 text 或跨块拼接 Markdown', () => {
  const array = [{type:'text', text:'**粗体**', extra:{source:7}}, {type:'image', text:'不能伪装正文', url:'file:///C:/private'},
    '# 下一块', {type:'text', text:'结束'}];
  const html = render('assistant', array);
  assert.match(html, /<strong>粗体<\/strong>/);
  assert.match(html, /查看原始文本块/);
  assert.match(html, /&quot;source&quot;: 7/);
  assert.match(html, /&quot;type&quot;: &quot;image&quot;/);
  assert.ok(html.indexOf('粗体') < html.indexOf('不能伪装正文'));
  assert.ok(html.indexOf('不能伪装正文') < html.indexOf('<h1>下一块'));
  const separated = render('assistant', ['**开头', {type:'unknown'}, '末尾**']);
  assert.doesNotMatch(separated, /<strong>/);
  assert.match(render('assistant', []), /复制完整内容/);
});

test('Windows 盘符与 UNC、定义引用保留原路径，不生成 href/src 或远程图片请求', () => {
  const raw = String.raw`[报告](C:\work\reports\one.pdf)

![预览](\\server\share\result.png)

[相对](reports\one.pdf)

[定义][report]

[report]: <C:\work\two files\report.pdf>

![远程](https://example.org/a.png)

[恶意](javascript:alert%281%29) [网页](https://example.org/path)`;
  const html = render('assistant', raw);
  assert.ok(html.includes(String.raw`C:\work\reports\one.pdf`));
  assert.ok(html.includes(String.raw`\\server\share\result.png`));
  assert.ok(html.includes(String.raw`C:\work\two files\report.pdf`));
  assert.doesNotMatch(html, / href=| src=|<img|<iframe/);
  assert.match(html, /网页图片未自动加载/);
  assert.match(html, /未支持的链接（只读）/);
});

test('代码完整原文、真实语言文件名、未闭合围栏以及预览复制有明确范围', () => {
  const raw = '```python filename="scripts/main.py"\n  x = 1\n\nprint(x)\n```';
  const html = render('assistant', raw);
  assert.match(html, /scripts\/main.py · python/);
  assert.ok(html.includes('<code>  x = 1\n\nprint(x)</code>'));
  assert.doesNotMatch(html, /line-number/);
  const unfinished = render('assistant', '```\n  原样\n  未闭合', {preview:true});
  assert.ok(unfinished.includes('<code>  原样\n  未闭合</code>'));
  assert.match(unfinished, /复制当前片段/);
  assert.doesNotMatch(unfinished, /复制完整内容/);
});

test('原始 HTML 文本化，GFM 表格与只读任务可见，脚注按消息隔离', () => {
  const source = '<script>alert(1)</script>\n\n<iframe src="https://bad.invalid"></iframe>\n\n'
    + '| A | B |\n| --- | --- |\n| 1 | 2 |\n\n- [x] 完成\n\n说明[^1]\n\n[^1]: 脚注';
  const first = render('assistant', source);
  assert.match(first, /&lt;script&gt;alert\(1\)&lt;\/script&gt;/);
  assert.doesNotMatch(first, /<script|<iframe|<form/);
  assert.match(first, /class="markdown-table"/);
  assert.match(first, /type="checkbox"[^>]*disabled/);
  const second = render('assistant', source, {identity:'another-message'});
  const ids = [...first.matchAll(/ id="([^"]+)"/g)].map(match => match[1]);
  assert.ok(ids.length >= 2);
  for (const id of ids) assert.ok(!second.includes(`id="${id}"`));
});
