import { BackendSession, BackendRequestError, type WorkspaceIdentity, type WorkspaceResource } from './backend-client';

export type ImageState = {phase:'idle' | 'loading' | 'ready' | 'error';
  resource?:WorkspaceResource; url?:string; error?:string};
interface ImageReader {
  reference:string; listeners:Set<(state:ImageState) => void>;
  state:ImageState; controller:AbortController; image?:SharedImage;
}
interface SharedImage {
  resourceId:string; readers:Set<ImageReader>; controller:AbortController;
  promise:Promise<string>; url?:string;
}
interface BlobUrls {createObjectUrl:(blob:Blob) => string; revokeObjectUrl:(url:string) => void}

/** 只持有当前可见会话的图片；文件事实与 Blob 始终经过同一 BackendSession。 */
export class WorkspaceImages {
  private scope = new AbortController();
  private readers = new Map<string, ImageReader>();
  private images = new Map<string, SharedImage>();
  private workspaceQuery:Promise<WorkspaceIdentity> | null = null;
  private onLeaseEnd = () => this.disposeImages();
  constructor(private session:BackendSession | null,
    private urls:BlobUrls = {createObjectUrl:blob => URL.createObjectURL(blob), revokeObjectUrl:url => URL.revokeObjectURL(url)}) {
    session?.signal.addEventListener('abort', this.onLeaseEnd, {once:true});
    if (session?.signal.aborted) this.disposeImages();
  }

  watchImage(reference:string, receiveState:(state:ImageState) => void) {
    let reader = this.readers.get(reference);
    if (!reader) {
      reader = {reference, listeners:new Set(), state:{phase:'idle'}, controller:new AbortController()};
      this.readers.set(reference, reader);
    }
    const imageReader = reader;
    imageReader.listeners.add(receiveState);
    receiveState(imageReader.state);
    if (imageReader.state.phase === 'idle') void this.loadImage(imageReader);
    return {
      retryImageLoad:() => {if (imageReader.listeners.has(receiveState) && imageReader.state.phase !== 'loading') void this.loadImage(imageReader);},
      releaseImageReader:() => {
        imageReader.listeners.delete(receiveState);
        if (!imageReader.listeners.size) {
          imageReader.controller.abort(); this.releaseImage(imageReader);
          if (this.readers.get(reference) === imageReader) this.readers.delete(reference);
        }
      },
    };
  }

  private publishImageState(reader:ImageReader, state:ImageState) {
    reader.state = state;
    reader.listeners.forEach(receiveState => receiveState(state));
  }
  private releaseImage(reader:ImageReader) {
    const image = reader.image;
    reader.image = undefined;
    if (!image) return;
    image.readers.delete(reader);
    if (!image.readers.size) {
      image.controller.abort();
      if (image.url) this.urls.revokeObjectUrl(image.url);
      if (this.images.get(image.resourceId) === image) this.images.delete(image.resourceId);
    }
  }
  private async readWorkspace() {
    if (!this.workspaceQuery) {
      this.workspaceQuery = this.session!.getWorkspace(this.scope.signal).catch(error => {
        this.workspaceQuery = null; throw error;
      });
    }
    return this.workspaceQuery;
  }

  private async loadImage(reader:ImageReader) {
    if (!this.session || this.scope.signal.aborted) {
      this.publishImageState(reader, {phase:'error', error:'本地图片需要当前桌面后端连接；引用已保留。'});
      return;
    }
    this.releaseImage(reader);
    reader.controller.abort(); reader.controller = new AbortController();
    const signal = AbortSignal.any([this.scope.signal, reader.controller.signal]);
    this.publishImageState(reader, {phase:'loading'});
    let resource:WorkspaceResource | undefined;
    try {
      const workspace = await this.readWorkspace(); signal.throwIfAborted();
      resource = await this.session.resolveResource(reader.reference, signal);
      if (resource.workspace_id !== workspace.workspace_id) throw new Error('工作目录身份已变化，请重新连接后端');
      signal.throwIfAborted();
      let image = this.images.get(resource.resource_id);
      if (!image) {
        const controller = new AbortController();
        const imageResource:SharedImage = {resourceId:resource.resource_id, readers:new Set(), controller,
          promise:Promise.resolve('')};
        const imageSignal = AbortSignal.any([this.scope.signal, controller.signal]);
        imageResource.promise = this.session.readResourceImage(resource.resource_id, imageSignal).then(blob => {
          imageSignal.throwIfAborted();
          imageResource.url = this.urls.createObjectUrl(blob);
          return imageResource.url;
        });
        this.images.set(resource.resource_id, imageResource);
        image = imageResource;
      }
      reader.image = image; image.readers.add(reader);
      const url = await image.promise; signal.throwIfAborted();
      this.publishImageState(reader, {phase:'ready', resource, url});
    } catch (error) {
      if (signal.aborted) return;
      this.releaseImage(reader);
      const message = error instanceof BackendRequestError ? `HTTP ${error.status}：${error.detail}`
        : error instanceof Error ? error.message : String(error);
      this.publishImageState(reader, {phase:'error', resource, error:message});
    }
  }

  disposeImages() {
    this.scope.abort();
    this.session?.signal.removeEventListener('abort', this.onLeaseEnd);
    this.readers.forEach(reader => {reader.controller.abort(); this.releaseImage(reader);});
    this.readers.clear(); this.images.clear(); this.workspaceQuery = null;
  }
}

