import { useEffect, useId, useSyncExternalStore, type ReactNode } from 'react';
import { Check, Clock, Terminal, XCircle } from '@phosphor-icons/react';
import { runStatusLabels } from '../backend-client';
import type { ToolRecord } from '../tool-records';
import { ToolCardPreferences, type ToolSection } from '../tool-card-preferences';
import { ContentBlock } from './ContentViewer';
import { MessageBody, type ContentView } from './MessageBody';

export function ToolCard({record, preferences, onView}: {
  record:ToolRecord; preferences:ToolCardPreferences; onView:(view:ContentView) => void;
}) {
  const content = record.result?.record?.content;
  const failed = content?.status === 'error';
  useSyncExternalStore(preferences.subscribe, preferences.getSnapshot, preferences.getSnapshot);
  const expanded = preferences.read(record.identity, failed);
  const panelId = useId();
  useEffect(() => { preferences.observeFailure(record.identity, failed); }, [preferences, record.identity, failed]);
  const toggle = (section:ToolSection) => preferences.toggle(record.identity, section, failed);
  function section(field:Exclude<ToolSection, 'card'>, title:string, children:ReactNode) {
    return <div className="tool-section">
      <button className="tool-section-heading" aria-expanded={expanded[field]} aria-controls={`${panelId}-${field}`} onClick={() => toggle(field)}>
        {title}<span aria-hidden="true">{expanded[field] ? '−' : '+'}</span>
      </button>
      <div id={`${panelId}-${field}`} hidden={!expanded[field]}>{children}</div>
    </div>;
  }
  const returned = Boolean(record.result);
  const title = record.call?.value.name ?? content?.name ?? '工具结果';
  const ended = record.runStatus && ['completed', 'cancelled', 'error'].includes(record.runStatus);
  return <div className="tool-block" data-reading-anchor={`tool:${record.identity}`} data-tool-id={record.call?.value.id ?? content?.tool_call_id} data-tool-identity={record.identity}>
    <button className="tool-summary" aria-expanded={expanded.card} aria-controls={panelId} onClick={() => toggle('card')}>
      <Terminal size={17} /><strong>{title}</strong>
      <span className={`tool-status ${failed ? 'tool-error' : returned ? 'success' : 'tool-waiting'}`}>
        {failed ? <XCircle size={14} /> : returned ? <Check size={14} /> : <Clock size={14} />}
        {failed ? '工具失败' : returned ? '已返回' : '等待结果'}
      </span><span className="tool-toggle" aria-hidden="true">{expanded.card ? '−' : '+'}</span>
    </button>
    {!record.call && <p className="tool-note">未找到对应调用 · tool_call_id：{content?.tool_call_id}</p>}
    {!returned && ended && <p className="tool-note">所属运行已结束（{runStatusLabels[record.runStatus!]}），尚未收到工具结果。</p>}
    <div className="tool-content" id={panelId} hidden={!expanded.card}>
      <p className="tool-identity">运行 ID：{record.call?.message.record?.run_id ?? record.result?.record?.run_id}<br />
        tool_call_id：{record.call?.value.id ?? content?.tool_call_id}</p>
      {record.call && <>
        <p>调用 seq：{record.call.message.record?.seq}</p>
        {section('parameters', '参数', <ContentBlock title="工具参数 JSON" text={JSON.stringify(record.call.value.args, null, 2)} onView={onView} />)}
      </>}
      {record.result && <div className="tool">
        <p>结果 seq：{record.result.record?.seq}</p>
        {section('result', '结果正文', <>
          <p>原始 status：{content?.status}{content && Object.hasOwn(content, 'name') ? <> · 结果名称：{content.name === null ? 'null' : JSON.stringify(content.name)}</> : null}</p>
          {content?.content === '' || Array.isArray(content?.content) && content.content.length === 0
            ? <p>已返回，正文为空</p> : null}
          <div className="tool-result-body"><MessageBody role="tool" content={record.result.content ?? record.result.text}
            identity={record.identity} onView={onView} /></div>
        </>)}
      </div>}
      {content && Object.hasOwn(content, 'artifact') && content.artifact != null && section('artifact', '附加数据',
        <ContentBlock title={typeof content.artifact === 'string' ? '附加数据原文' : '附加数据 JSON'}
          text={typeof content.artifact === 'string' ? content.artifact : JSON.stringify(content.artifact, null, 2)} onView={onView} />)}
      {section('raw', '原始记录', <>
        {record.call && <ContentBlock title="调用记录 JSON" text={JSON.stringify(record.call.message.record, null, 2)} onView={onView} />}
        {record.result && <ContentBlock title="结果记录 JSON" text={JSON.stringify(record.result.record, null, 2)} onView={onView} />}
      </>)}
    </div>
  </div>;
}
