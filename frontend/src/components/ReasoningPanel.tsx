import { useState, type ReactNode } from 'react';
import { Brain, CaretDown } from '@phosphor-icons/react';
import { ContentBlock, CopyContent } from './ContentViewer';
import type { ContentView } from './MessageBody';
import { Reasoning, ReasoningContent, ReasoningTrigger } from '@/components/ai-elements/reasoning';

/** Only explicit, readable reasoning blocks become prose; other blocks stay raw. */
export function readReasoningText(block: Record<string, unknown>): string | null {
  if (block.type === 'thinking' && typeof block.thinking === 'string') return block.thinking;
  if (block.type !== 'reasoning') return null;
  if (typeof block.reasoning === 'string') return block.reasoning;
  if (Array.isArray(block.summary) && block.summary.length > 0
    && block.summary.every(part => part && typeof part === 'object' && !Array.isArray(part)
      && part.type === 'summary_text' && typeof part.text === 'string')) {
    return block.summary.map(part => part.text).join('\n\n');
  }
  return null;
}

export function ReasoningPanel({text, source, preview, generating, onView, children}: ContentView & {
  source: Record<string, unknown>; onView:(view:ContentView) => void; children:ReactNode;
}) {
  const [isExpanded, setIsExpanded] = useState(true);
  return <Reasoning asChild open={isExpanded} onOpenChange={setIsExpanded}
    isStreaming={Boolean(preview && generating !== false)}>
    <section className="reasoning-panel" aria-label="思考链路">
    <ReasoningTrigger className="reasoning-toggle">
      <span className="reasoning-heading">
        <Brain size={16} aria-hidden="true" />
        <span className="reasoning-title">思考链路 / Reasoning Process</span>
        {preview && <span className="reasoning-status">{generating === false ? '预览' : '生成中'}</span>}
      </span>
      <CaretDown className="reasoning-chevron" size={16} aria-hidden="true" />
    </ReasoningTrigger>
    <ReasoningContent className="reasoning-body">
      <div className="reasoning-text message-text">{text.trim() ? children : <p>未提供思考文本。</p>}</div>
      <div className="reasoning-actions content-actions">
        <button className="text-button" onClick={() => onView({title:'完整思考内容', text, preview, generating})}>查看完整思考</button>
        <CopyContent text={text} label={preview ? '复制当前思考片段' : '复制思考内容'} />
      </div>
      <details className="raw-content">
        <summary>查看原始思考块</summary>
        <ContentBlock title="原始思考块 JSON" text={JSON.stringify(source, null, 2)}
          preview={preview} generating={generating} onView={onView} />
      </details>
    </ReasoningContent>
  </section>
  </Reasoning>;
}
