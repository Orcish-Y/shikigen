import { useState } from 'react';
import { Tool, ToolContent, ToolHeader, ToolOutput } from '../ai-elements/tool';
import { Button } from '../ui/button';
import type { ContentView } from '../MessageBody';
import { formatToolValue, type ToolResult } from '../../tool-library';

export function ToolTestResult({result, inputs, onView}: {
  result: ToolResult; inputs: Record<string, unknown>; onView: (view: ContentView) => void;
}) {
  const [copy, setCopy] = useState<string | null>(null);
  const text = formatToolValue(result);
  return <Tool defaultOpen>
    <ToolHeader status={result.status}/>
    <ToolContent>
      <p>耗时：{result.duration_ms.toFixed(1)} ms</p>
      <details><summary>实际输入</summary><pre>{formatToolValue(inputs)}</pre></details>
      <h3>返回数据</h3>{result.data_available === false ? <p>未取得返回数据</p> : <ToolOutput value={result.data}/>}
      {result.error !== null && <div role="alert"><p>{result.error.code}：{result.error.message}</p><pre>{formatToolValue(result.error)}</pre></div>}
      {'stdout' in result.details ? <section aria-label="Python 调试输出"><h3>调试输出</h3>
        <p>退出码：{String(result.details.exit_code)}{(result.details.stdout_truncated || result.details.stderr_truncated) ? ' · 调试输出已截断，保留最后 64 KiB' : ''}</p>
        <details open><summary>stdout</summary><pre>{String(result.details.stdout)}</pre></details>
        <details open><summary>stderr</summary><pre>{String(result.details.stderr)}</pre></details>
      </section> : null}
      <details><summary>{'remote_name' in result.details ? 'MCP 原始返回与来源' : 'stdout' in result.details ? '完整执行详情' : 'HTTP 详情'}</summary><pre>{formatToolValue(result.details)}</pre></details>
      <div className="tool-actions">
        <Button variant="outline" type="button" onClick={() => onView({title:'完整工具结果',text})}>查看完整结果</Button>
        <Button variant="outline" type="button" onClick={async () => {
          try {await navigator.clipboard.writeText(text); setCopy('已复制');}
          catch {setCopy('复制失败，可手动选择');}
        }}>复制完整结果</Button>
      </div>
      {copy && <p role="status">{copy}</p>}
    </ToolContent>
  </Tool>;
}
