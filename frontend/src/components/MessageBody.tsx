import { Component, createContext, useContext, useState, type ReactNode } from 'react';
import Markdown, { type Components } from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeSanitize from 'rehype-sanitize';
import { invoke, isTauri } from '@tauri-apps/api/core';
import { codeTitle, messagePrefix, messageSchema, referenceKind, rehypeFootnoteScope, remarkMessageContent } from '../markdown-policy';
import { ContentBlock, CopyContent } from './ContentViewer';

export type ContentView = { title: string; text: string; preview?: boolean; generating?:boolean;
  approval?:{runId:string; identity:string; namespace?:string; description?:string | null} };
export type MessageRole = 'assistant' | 'user' | 'tool';

function Reference({reference, children, image = false}: {reference:string; children:ReactNode; image?:boolean}) {
  const [error, setError] = useState('');
  const kind = referenceKind(reference);
  if (kind === 'web' && !image) return <span className="markdown-reference">
    <button className="markdown-link" title={reference} onClick={() => {
      setError('');
      if (!isTauri()) { setError('网页打开仅在桌面应用中可用'); return; }
      void invoke('open_web_url', {url:reference}).catch(failure => {
        setError(`打开失败：${typeof failure?.message === 'string' ? failure.message : String(failure)}`);
      });
    }}>{children}</button>
    {error && <span className="content-error" role="alert">{error}</span>}
  </span>;
  return <span className="markdown-reference readonly-reference">
    <span>{children}</span>
    <span className="reference-path">{reference}</span>
    <span className="reference-note">{image && kind === 'web' ? '网页图片未自动加载'
      : kind === 'local' ? '本地资源（只读引用）' : '未支持的链接（只读）'}</span>
    <CopyContent text={reference} label="复制引用" />
  </span>;
}

class RenderBoundary extends Component<{text:string; children:ReactNode}, {failed:boolean}> {
  state = {failed:false};
  static getDerivedStateFromError() { return {failed:true}; }
  render() {
    return this.state.failed ? <><p className="content-error" role="alert">正文呈现失败，原文已保留。</p>
      <div className="plain-content">{this.props.text}</div></> : this.props.children;
  }
}

const MarkdownContext = createContext<{
  identity:string; preview?:boolean; generating?:boolean; onView:(view:ContentView) => void;
} | null>(null);

// Keep renderer identities stable as the conversation and overlay state update.
// Context supplies fresh actions without replacing focused buttons or selections.
const markdownComponents: Components = {
  table:({children}) => <div className="markdown-table" tabIndex={0}><table>{children}</table></div>,
  li:({node, children, className}) => <li id={typeof node?.properties.id === 'string' ? node.properties.id : undefined}
    tabIndex={node?.properties.id ? -1 : undefined} className={className}>{children}</li>,
  input:({checked}) => <input type="checkbox" disabled checked={checked ?? false} readOnly />,
  pre:function MarkdownCode({node}) {
    const {preview, generating, onView} = useContext(MarkdownContext)!;
    const code = node?.children.find(child => child.type === 'element' && child.tagName === 'code');
    const props = code?.type === 'element' ? code.properties : {};
    return <ContentBlock title={codeTitle(String(props.dataLanguage ?? ''), String(props.dataMeta ?? ''))}
      text={String(props.dataCode ?? '')} preview={preview} generating={generating} onView={onView} />;
  },
  a:function MarkdownLink({node, children, href}) {
    const {identity} = useContext(MarkdownContext)!;
    const reference = node?.properties.dataReference;
    if (typeof reference === 'string') return <Reference reference={reference}>{children}</Reference>;
    // Only generated message-scoped footnotes keep an anchor target.
    return <button className="markdown-link" id={typeof node?.properties.id === 'string' ? node.properties.id : undefined} onClick={() => {
      if (href?.startsWith(`#${messagePrefix(identity)}`)) {
        const target = document.getElementById(href.slice(1));
        target?.scrollIntoView({block:'nearest'}); target?.focus();
      }
    }}>{children}</button>;
  },
  img:({node, alt}) => <Reference image reference={String(node?.properties.dataReference ?? '')}>{alt || '图片'}</Reference>,
};

function AgentText({text, identity, preview, generating, onView}: ContentView & {identity:string; onView:(view:ContentView) => void}) {
  return <RenderBoundary key={text} text={text}>
    <MarkdownContext.Provider value={{identity, preview, generating, onView}}>
    <Markdown remarkPlugins={[remarkGfm, remarkMessageContent]}
      rehypePlugins={[[rehypeFootnoteScope, messagePrefix(identity)], [rehypeSanitize, messageSchema]]}
      remarkRehypeOptions={{clobberPrefix:messagePrefix(identity), footnoteLabel:'脚注'}}
      components={markdownComponents}
      urlTransform={url => url.startsWith(`#${messagePrefix(identity)}`) ? url : ''}>{text}</Markdown>
    </MarkdownContext.Provider>
  </RenderBoundary>;
}

export function MessageBody({role, content, identity, preview, generating, onView}: {
  role: MessageRole; content: unknown; identity: string; preview?: boolean; generating?:boolean;
  onView: (view: ContentView) => void;
}) {
  const text = typeof content === 'string' ? content : JSON.stringify(content, null, 2);
  function block(value:unknown, index:number): ReactNode {
    if (typeof value === 'string') return role === 'assistant'
      ? <AgentText key={index} title="正文" text={value} identity={`${identity}:${index}`} preview={preview} generating={generating} onView={onView} />
      : <div key={index} className="plain-content">{value}</div>;
    if (value && typeof value === 'object' && !Array.isArray(value)
      && 'type' in value && value.type === 'text' && 'text' in value && typeof value.text === 'string') {
      return <div key={index}>{block(value.text, index)}
        {Object.keys(value).some(key => key !== 'type' && key !== 'text') && <details className="raw-content">
          <summary>查看原始文本块</summary><ContentBlock title="原始文本块 JSON" text={JSON.stringify(value, null, 2)} preview={preview} generating={generating} onView={onView} />
        </details>}
      </div>;
    }
    return <ContentBlock key={index} title="内容块 JSON" text={JSON.stringify(value, null, 2)} preview={preview} generating={generating} onView={onView} />;
  }
  return <div className="message-content">
    <div className="message-text">{Array.isArray(content) ? content.map(block) : block(content, 0)}</div>
    <div className="message-content-actions">
      <button className="text-button" onClick={() => onView({title:'完整正文', text, preview, generating})}>查看完整内容</button>
      <CopyContent text={text} label={preview ? '复制当前片段' : '复制完整内容'} />
    </div>
  </div>;
}
