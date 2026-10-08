import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { MessageBody } from '../src/components/MessageBody.tsx';
import { FileOpenConfirmation } from '../src/components/WorkspaceFileOpen.tsx';

const render = (role, content, extra = {}) => renderToStaticMarkup(React.createElement(MessageBody,
  {role, content, identity:'thread:run:message', onView:() => {}, ...extra}));

test('本地文件与图片打开入口绑定原消息和内容块身份', () => {
  const html = render('assistant', ['[报告](notes/report.txt)', '![图片](images/tall.png)']);
  assert.match(html, /data-file-message-identity="thread:run:message:0"/);
  assert.match(html, /data-file-message-identity="thread:run:message:1"/);
  const otherMessageMarkup = render('assistant', '[报告](notes/report.txt)', {identity:'another-message'});
  assert.match(otherMessageMarkup, /data-file-message-identity="another-message:0"/);
  assert.doesNotMatch(otherMessageMarkup, /data-file-message-identity="thread:run:message:0"/);
});

test('明确目录引用只读且保留复制，普通文件仍可准备', () => {
  const html = render('assistant', '[目录](notes/) ![目录图片](notes/) [文件](notes/report.txt)');
  assert.match(html, /目录引用暂不支持打开（只读）/);
  assert.doesNotMatch(html, /data-file-reference="notes\/"/);
  assert.equal(html.match(/目录引用暂不支持打开（只读）/g).length, 2);
  assert.match(html, /data-file-reference="notes\/report.txt"/);
  assert.match(html, /复制引用/);
});

test('核实失败的本地引用明确只读，没有确认打开入口', () => {
  const html = renderToStaticMarkup(React.createElement(FileOpenConfirmation, {
    view:{phase:'error', reference:'notes', messageIdentity:'message-1:0', intent:null,
      error:'HTTP 422：首版不支持目录资源'},
    onClose:() => {}, onConfirm:() => {}, onPrepare:() => {},
  }));
  assert.match(html, /本次准备未打开文件，当前引用只读/);
  assert.match(html, /HTTP 422：首版不支持目录资源/);
  assert.match(html, /复制引用/);
  assert.doesNotMatch(html, /确认打开/);
});

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

test('思考块使用独立折叠面板并保留正文顺序、元数据和原文入口', () => {
  const content = [{type:'thinking', thinking:'• **分析需求**：保留消息身份。', signature:'original-signature'},
    {type:'text', text:'这是最终回答。'}, {type:'reasoning', reasoning:'**安全约束**：保持原始记录。', extras:{source:'provider'}}];
  const original = structuredClone(content);
  const html = render('assistant', content);
  assert.equal(html.match(/class="reasoning-panel"/g).length, 2);
  assert.match(html, /aria-expanded="true" aria-controls="[^"]+"/);
  assert.match(html, /<strong>分析需求<\/strong>：/);
  assert.match(html, /<strong>安全约束<\/strong>：/);
  assert.ok(html.indexOf('<strong>分析需求') < html.indexOf('这是最终回答。'));
  assert.ok(html.indexOf('这是最终回答。') < html.indexOf('<strong>安全约束'));
  assert.match(html, /查看完整思考/);
  assert.match(html, /复制思考内容/);
  assert.match(html, /查看原始思考块/);
  assert.match(html, /original-signature/);
  assert.match(html, /&quot;source&quot;: &quot;provider&quot;/);
  assert.deepEqual(content, original);
  const controls = [...html.matchAll(/aria-controls="([^"]+)"/g)].map(match => match[1]);
  assert.equal(new Set(controls).size, 2);
  for (const id of controls) assert.ok(html.includes(`id="${id}"`));
});

test('思考摘要可读，未知／加密／错误结构仍显示完整 JSON，其他角色不解析思考', () => {
  const summary = {type:'reasoning', summary:[{type:'summary_text', text:'第一阶段'}, {type:'summary_text', text:'第二阶段'}]};
  const html = render('assistant', [summary]);
  assert.match(html, /class="reasoning-panel"/);
  assert.match(html, /<p[^>]*>第一阶段<\/p>/);
  assert.match(html, /<p[^>]*>第二阶段<\/p>/);
  for (const block of [{type:'reasoning', encrypted_content:'opaque'}, {type:'thinking', thinking:42},
    {type:'reasoning', summary:[{type:'unknown', text:'保留未知摘要'}]}, {type:'unknown', reasoning:'不要猜'}]) {
    const raw = render('assistant', [block]);
    assert.doesNotMatch(raw, /class="reasoning-panel"/);
    assert.match(raw, /内容块 JSON/);
  }
  for (const role of ['user', 'tool']) assert.doesNotMatch(render(role, [summary]), /class="reasoning-panel"/);
});

test('思考预览范围明确，空文本可读，HTML 与远程图片沿用正文安全策略', () => {
  const html = render('assistant', [{type:'reasoning', reasoning:'<script>alert(1)</script>\n\n![远程](https://example.org/a.png)'}],
    {preview:true, generating:true});
  assert.match(html, /class="reasoning-status">生成中/);
  assert.match(html, /复制当前思考片段/);
  assert.doesNotMatch(html, /复制思考内容|复制完整内容/);
  assert.match(html, /&lt;script&gt;/);
  assert.match(html, /网页图片未自动加载/);
  assert.doesNotMatch(html, /<script|<img/);
  assert.match(render('assistant', [{type:'thinking', thinking:'  '}]), /未提供思考文本/);
  assert.match(render('assistant', [{type:'reasoning', reasoning:'当前片段'}], {preview:true, generating:false}),
    /class="reasoning-status">预览/);
});
