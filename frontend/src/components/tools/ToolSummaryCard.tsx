import { Globe } from '@phosphor-icons/react';
import type { HttpToolDefinition, ToolDraft } from '../../tool-library';

export function ToolSummaryCard({tool, initial, dirty, version}: {tool:HttpToolDefinition | null; initial:ToolDraft; dirty:boolean; version:string}) {
  return <section className="tool-summary-card" aria-label="工具概览">
    <div className="tool-summary-icon"><Globe size={25}/></div>
    <div className="tool-summary-information">
      <div className="tool-summary-title"><h1>{initial.display_name || '创建 HTTP 工具'}</h1>
        <code className="tool-meta-tag">{initial.name || '调用名称自动生成'}</code>
        <span className={`tool-meta-tag ${initial.enabled ? 'enabled' : ''}`}>{initial.enabled ? '已启用' : '已禁用'}{dirty && '（草稿）'}</span>
        {dirty && <span className="tool-meta-tag unsaved">未保存修改</span>}
      </div>
      <p>{initial.description || '配置 HTTP 请求，测试当前草稿并查看真实响应。'}</p>
      <div className="tool-summary-tags"><span className="tool-meta-tag">HTTP 请求</span><span className="tool-meta-tag">{initial.method}</span>
        {initial.input_schema?.properties?.body && <span className="tool-meta-tag">JSON 请求体</span>}<span className="tool-meta-tag">超时 {initial.timeout_seconds} 秒</span></div>
      {tool && <div className="tool-summary-id"><span>ID</span><code>{tool.id}</code></div>}
    </div>
    {tool && <dl className="tool-system-fields"><dt>创建时间</dt><dd><time dateTime={tool.created_at} title={tool.created_at}>{new Date(tool.created_at).toLocaleString()}</time></dd>
      <dt>更新时间</dt><dd><time dateTime={tool.updated_at} title={tool.updated_at}>{new Date(tool.updated_at).toLocaleString()}</time></dd>
      <dt>读取版本</dt><dd><code title={version}>{version}</code></dd></dl>}
  </section>;
}
