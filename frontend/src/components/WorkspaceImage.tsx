import { createContext, useContext, useLayoutEffect, useEffect, useState, useRef, type ReactNode } from 'react';
import type { BackendSession } from '../backend-client';
import { WorkspaceImages, type ImageState } from '../workspace-images';
import { CopyContent } from './ContentViewer';
import type { ContentView } from './MessageBody';

const ImageContext = createContext<WorkspaceImages | null>(null);
export function WorkspaceImageProvider({session, threadId, isVisible, children}: {
  session:BackendSession | null; threadId:string | null; isVisible:boolean; children:ReactNode;
}) {
  const [images, setImages] = useState<WorkspaceImages | null>(null);
  useLayoutEffect(() => {
    const imageScope = isVisible ? new WorkspaceImages(session) : null;
    setImages(imageScope);
    return () => imageScope?.disposeImages();
  }, [session, threadId, isVisible]);
  return <ImageContext.Provider value={images}>{children}</ImageContext.Provider>;
}

export function WorkspaceImage({reference, alt, onView}: {
  reference:string; alt:string; onView:(view:ContentView) => void;
}) {
  const images = useContext(ImageContext);
  const [state, setState] = useState<ImageState>({phase:'idle'});
  const [decodeError, setDecodeError] = useState('');
  const [areCoordinatesVisible, setCoordinatesVisible] = useState(false);
  const reader = useRef<ReturnType<WorkspaceImages['watchImage']> | null>(null);
  useEffect(() => {
    setState({phase:'idle'}); setDecodeError('');
    const subscription = images?.watchImage(reference, next => {setState(next); setDecodeError('');}) ?? null;
    reader.current = subscription;
    return () => {subscription?.releaseImageReader(); if (reader.current === subscription) reader.current = null;};
  }, [images, reference]);
  return <span className="workspace-image markdown-reference" aria-label={`本地图片：${alt}`}>
    {state.phase === 'ready' && state.url && <img src={state.url} alt={alt}
      onError={() => setDecodeError('图片解码失败，原引用已保留；可重试读取当前文件。')} />}
    <span className="workspace-image-heading">{alt || '本地图片'}</span>
    <span className="reference-path">{reference}</span>
    <span className="reference-note">当前磁盘内容 · 非生成时快照</span>
    {(state.phase === 'idle' || state.phase === 'loading') && <span className="reference-note">{images ? '正在读取本地图片…' : '本地图片（只读引用）'}</span>}
    {(state.error || decodeError) && <span className="content-error" role="alert">{decodeError || state.error}</span>}
    <span className="content-actions">
      {state.phase === 'ready' && state.url && state.resource && !decodeError && <button className="text-button" onClick={() => onView({
        title:alt || state.resource!.name, text:reference,
        image:{url:state.url!, reference, resource:state.resource!},
      })}>查看完整图片</button>}
      {(state.phase === 'error' || decodeError) && <button className="text-button" onClick={() => reader.current?.retryImageLoad()}>重试读取</button>}
      <CopyContent text={reference} label="复制引用" />
    </span>
    {state.resource && <span className="resource-coordinates">
      <button className="text-button" aria-expanded={areCoordinatesVisible} onClick={() => setCoordinatesVisible(value => !value)}>核对实际文件</button>
      {areCoordinatesVisible && <span className="resource-coordinate-body"><span className="reference-path">{state.resource.absolute_path}</span>
      <span className="reference-note">{state.resource.size} 字节 · 修改于 {state.resource.modified_at}</span>
      <CopyContent text={state.resource.absolute_path} label="复制实际路径" /></span>}
    </span>}
  </span>;
}

