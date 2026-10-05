import { useState } from 'react';
import { Copy, FileCode } from '@phosphor-icons/react';
import type { ContentView } from './MessageBody';

export function CopyContent({text, label = '复制完整内容'}: {text:string; label?:string}) {
  const [state, setState] = useState<string | null>(null);
  return <span className="copy-control">
    <button className="text-button" aria-label={label} onClick={async () => {
      try { await navigator.clipboard.writeText(text); setState('已复制'); }
      catch { setState('复制失败，可手动选择'); }
    }}><Copy size={14} />{state === '已复制' ? state : label}</button>
    {state === '复制失败，可手动选择' && <span role="status">{state}</span>}
  </span>;
}

export function ContentBlock({title, text, preview, generating, onView}: ContentView & {onView:(view:ContentView) => void}) {
  return <div className="code-block content-block">
    <div className="block-heading">
      <span><FileCode size={16} />{title}</span>
      <div className="content-actions">
        <button className="text-button" onClick={() => onView({title, text, preview, generating})}>查看完整内容</button>
        <CopyContent text={text} label={preview ? '复制当前片段' : '复制'} />
      </div>
    </div>
    <pre tabIndex={0} aria-label={title}><code>{text}</code></pre>
  </div>;
}

export function ContentViewer({view}: {view:ContentView}) {
  return <div className="content-viewer">
    {view.preview && <p>{view.generating === false ? '预览 · 尚未读取保存事实，以下为当前片段。' : '生成中 · 尚未保存，以下为当前片段。'}</p>}
    <CopyContent text={view.text} label={view.preview ? '复制当前片段' : '复制完整内容'} />
    <pre tabIndex={0} aria-label={view.title}>{view.text}</pre>
  </div>;
}
