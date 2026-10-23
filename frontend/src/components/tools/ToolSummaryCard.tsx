import { useState } from 'react';
import { Globe } from '@phosphor-icons/react';
import { Button } from '../ui/button';
import type { AnyToolDefinition, ToolDraft } from '../../tool-library';

export function ToolSummaryCard({tool, initial, dirty, version}: {tool:AnyToolDefinition | null; initial:ToolDraft; dirty:boolean; version:string}) {
  const [copy,setCopy]=useState<string | null>(null);
  const source=tool?.kind === 'python' ? `Python · 本地源码 main · ${tool.code_path}`
    : tool?.kind === 'mcp' ? `MCP · ${tool.connection_id} / ${tool.remote_name}`
    : tool?.kind === 'http' ? `HTTP · ${tool.openapi_source ? 'OpenAPI 导入' : '手工创建'} · ${tool.url}` : null;
  return <section className="tool-summary-card" aria-label="工具概览">
    <div className="tool-summary-icon"><Globe size={25}/></div>
    <div className="tool-summary-information">
      <div className="tool-summary-title"><h1>{initial.display_name || `创建 ${initial.kind === 'python' ? 'Python' : 'HTTP'} 工具`}</h1>
        <code className="tool-meta-tag">{initial.name || '调用名称自动生成'}</code>
        <span className={`tool-meta-tag ${initial.enabled ? 'enabled' : ''}`}>{initial.enabled ? '已启用' : '已禁用'}{dirty && '（草稿）'}</span>
        {dirty && <span className="tool-meta-tag unsaved">未保存修改</span>}
      </div>
      <p>{initial.description || (initial.kind === 'python' ? '编辑 main 源码，预览参数并在本机子进程测试。' : initial.kind === 'mcp' ? '调用所选 MCP 服务的远端工具，并查看完整返回。' : '配置 HTTP 请求，测试当前草稿并查看真实响应。')}</p>
      <div className="tool-summary-tags"><span className="tool-meta-tag">{initial.kind === 'python' ? 'Python · main' : initial.kind === 'mcp' ? `MCP · ${initial.remote_name}` : 'HTTP 请求'}</span>{initial.kind === 'http' && <span className="tool-meta-tag">{initial.method}</span>}
        {initial.kind === 'http' && initial.input_schema?.properties?.body && <span className="tool-meta-tag">JSON 请求体</span>}<span className="tool-meta-tag">超时 {initial.timeout_seconds} 秒</span></div>
      {source && <p className="tool-summary-source" aria-label="工具来源">来源：{source}</p>}
      {tool && <div className="tool-summary-id"><span>稳定 ID</span><code>{tool.id}</code>
        <Button type="button" size="sm" variant="outline" onClick={async () => {
          try {await navigator.clipboard.writeText(tool.id);setCopy('工具 ID 已复制');}
          catch {setCopy('复制失败，可手动选择 ID');}
        }}>复制工具 ID</Button>{copy && <span role="status">{copy}</span>}</div>}
    </div>
    {tool && <dl className="tool-system-fields"><dt>创建时间</dt><dd><time dateTime={tool.created_at} title={tool.created_at}>{new Date(tool.created_at).toLocaleString()}</time></dd>
      <dt>更新时间</dt><dd><time dateTime={tool.updated_at} title={tool.updated_at}>{new Date(tool.updated_at).toLocaleString()}</time></dd>
      <dt>读取版本</dt><dd><code title={version}>{version}</code></dd></dl>}
  </section>;
}
