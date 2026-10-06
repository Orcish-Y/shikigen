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
  if (view.image) return <div className="content-viewer image-viewer">
    <p>当前磁盘内容 · 非生成时快照</p>
    <img src={view.image.url} alt={view.title} />
    <p>原始引用</p><pre tabIndex={0}>{view.image.reference}</pre>
    <CopyContent text={view.image.reference} label="复制引用" />
    <p>实际文件</p><pre tabIndex={0}>{view.image.resource.absolute_path}</pre>
    <CopyContent text={view.image.resource.absolute_path} label="复制实际路径" />
    <details><summary>完整文件元数据</summary><pre tabIndex={0}>{JSON.stringify(view.image.resource, null, 2)}</pre></details>
  </div>;
  return <div className="content-viewer">
    {view.approval?.namespace !== undefined && <div className="approval-description">
      <p>来源：{view.approval.namespace || '主流程'}（namespace：{JSON.stringify(view.approval.namespace)}）</p>
      <p>说明：{view.approval.description || '未提供说明'}</p>
    </div>}
    {view.preview && <p>{view.generating === false ? '预览 · 尚未读取保存事实，以下为当前片段。' : '生成中 · 尚未保存，以下为当前片段。'}</p>}
    <CopyContent text={view.text} label={view.preview ? '复制当前片段' : '复制完整内容'} />
    <pre tabIndex={0} aria-label={view.title}>{view.text}</pre>
  </div>;
}
