import { Globe } from '@phosphor-icons/react';
import type { HttpToolDefinition, ToolDraft } from '../../tool-library';

export function ToolSummaryCard({tool, initial, dirty}: {tool:HttpToolDefinition | null; initial:ToolDraft; dirty:boolean}) {
  return <section className="tool-summary-card" aria-label="工具概览">
    <div className="tool-summary-icon"><Globe size={25}/></div>
    <div className="tool-summary-information">
      <div className="tool-summary-title"><h1>{tool?.display_name || '创建 HTTP 工具'}</h1>
        <code className="tool-meta-tag">{tool?.name || initial.name || '调用名称自动生成'}</code>
        {tool && <span className={`tool-meta-tag ${tool.enabled ? 'enabled' : ''}`}>{tool.enabled ? '已启用' : '已禁用'}</span>}
        {dirty && <span className="tool-meta-tag unsaved">未保存修改</span>}
      </div>
      <p>{tool?.description || '按保存的请求地址发起 GET 请求，并查看完整的真实响应。'}</p>
      <div className="tool-summary-tags"><span className="tool-meta-tag">HTTP 请求</span><span className="tool-meta-tag">GET</span>
        <span className="tool-meta-tag">无认证</span><span className="tool-meta-tag">超时 {initial.timeout_seconds} 秒</span></div>
      {tool && <div className="tool-summary-id"><span>ID</span><code>{tool.id}</code></div>}
    </div>
    {tool && <dl className="tool-system-fields"><dt>创建时间</dt><dd><time dateTime={tool.created_at} title={tool.created_at}>{new Date(tool.created_at).toLocaleString()}</time></dd>
      <dt>更新时间</dt><dd><time dateTime={tool.updated_at} title={tool.updated_at}>{new Date(tool.updated_at).toLocaleString()}</time></dd></dl>}
  </section>;
}
