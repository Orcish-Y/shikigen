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
      <h3>返回数据</h3><ToolOutput value={result.data}/>
      {result.error !== null && <div role="alert"><p>{result.error.code}：{result.error.message}</p><pre>{formatToolValue(result.error)}</pre></div>}
      <details><summary>HTTP 详情</summary><pre>{formatToolValue(result.details)}</pre></details>
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
