import type { Session } from '../data/demo';
import { CopyContent } from './ContentViewer';

export function ConversationIdentity({session}: {session: Session}) {
  return <div className="conversation-identity">
    <section><h3>完整标题</h3><p className="identity-title">{session.title}</p>
      <CopyContent text={session.title} label="复制会话标题"/>
    </section>
    <section><h3>会话 ID</h3><pre tabIndex={0}>{session.id}</pre>
      <CopyContent text={session.id} label="复制会话 ID"/>
    </section>
    <section><h3>更新时间</h3>{session.time ? <>
      <p>{session.time.local}</p>
      <CopyContent text={session.time.local} label="复制完整本地时间"/>
      {session.time.utc && <><pre tabIndex={0}>UTC：{session.time.utc}</pre>
        <CopyContent text={session.time.utc} label="复制更新时间 UTC"/></>}
      <p>服务端原值：{session.time.original || '未提供'}</p>
    </> : <p>示例预览没有真实更新时间</p>}</section>
  </div>;
}
