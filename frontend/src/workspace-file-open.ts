import type { WorkspaceResource } from './backend-client';

export interface PreparedFileOpen extends WorkspaceResource {
  request_id:string; startup_id:string; workspace_root:string;
}
export interface FileOpenView {
  phase:'idle' | 'preparing' | 'prepared' | 'opening' | 'accepted' | 'error';
  reference:string; messageIdentity:string; intent:PreparedFileOpen | null; error:string;
}
export type InvokeFileCommand = (command:string, commandArguments:Record<string,string>) => Promise<unknown>;

function readFailureMessage(failure:unknown):string {
  return failure && typeof failure === 'object' && 'message' in failure && typeof failure.message === 'string'
    ? failure.message : String(failure);
}

function verifyIntent(payload:unknown, startupId:string):PreparedFileOpen {
  const intent = payload as PreparedFileOpen;
  if (!intent || typeof intent !== 'object' || intent.startup_id !== startupId
    || ['request_id','workspace_id','workspace_root','resource_id','absolute_path','relative_path','name','version'].some(field =>
      typeof intent[field as keyof PreparedFileOpen] !== 'string' || !intent[field as keyof PreparedFileOpen])
    || intent.kind !== 'file' || !Number.isSafeInteger(intent.size) || intent.size < 0
    || typeof intent.modified_at !== 'string' || !Number.isFinite(Date.parse(intent.modified_at))
    || !(intent.mime_type === null || typeof intent.mime_type === 'string') || typeof intent.can_preview !== 'boolean') {
    throw new Error('宿主返回的文件身份或元数据无效，请重新准备');
  }
  return intent;
}

/** One visible conversation/host lease. Only an explicit confirmation opens. */
export class WorkspaceFileOpening {
  view:FileOpenView = {phase:'idle', reference:'', messageIdentity:'', intent:null, error:''};
  private operationGeneration = 0;
  private isDisposed = false;
  private listeners = new Set<(view:FileOpenView) => void>();
  constructor(private startupId:string, private invokeCommand:InvokeFileCommand) {}

  subscribeFileOpen(receiveView:(view:FileOpenView) => void) {
    this.listeners.add(receiveView); receiveView(this.view);
    return () => {this.listeners.delete(receiveView);};
  }
  private publishView(view:FileOpenView) {
    this.view = view;
    for (const receiveView of this.listeners) receiveView(view);
  }
  private discardIntent(intent:unknown) {
    if (intent && typeof intent === 'object' && 'request_id' in intent && typeof intent.request_id === 'string') {
      void this.invokeCommand('discard_prepared_workspace_file', {requestId:intent.request_id}).catch(() => {});
    }
  }
  async prepareFileOpen(reference:string, messageIdentity:string) {
    if (this.isDisposed || this.view.phase === 'preparing' || this.view.phase === 'opening') return;
    this.discardIntent(this.view.intent);
    const operationGeneration = ++this.operationGeneration;
    this.publishView({phase:'preparing', reference, messageIdentity, intent:null, error:''});
    let payload:unknown;
    try {
      payload = await this.invokeCommand('prepare_workspace_file_open', {startupId:this.startupId, path:reference});
      if (this.isDisposed || operationGeneration !== this.operationGeneration) {this.discardIntent(payload); return;}
      this.publishView({phase:'prepared', reference, messageIdentity, intent:verifyIntent(payload, this.startupId), error:''});
    } catch (failure) {
      this.discardIntent(payload);
      if (!this.isDisposed && operationGeneration === this.operationGeneration)
        this.publishView({phase:'error', reference, messageIdentity, intent:null, error:readFailureMessage(failure)});
    }
  }
  async confirmFileOpen() {
    if (this.isDisposed || this.view.phase !== 'prepared' || !this.view.intent) return;
    const intent = this.view.intent;
    const operationGeneration = this.operationGeneration;
    this.publishView({...this.view, phase:'opening', error:''});
    try {
      const isAccepted = await this.invokeCommand('open_prepared_workspace_file', {requestId:intent.request_id});
      if (isAccepted !== true) throw new Error('系统打开结果未确认，请核对系统程序；不会自动再打开');
      if (!this.isDisposed && operationGeneration === this.operationGeneration) this.publishView({...this.view, phase:'accepted'});
    } catch (failure) {
      if (!this.isDisposed && operationGeneration === this.operationGeneration)
        this.publishView({...this.view, phase:'error', error:readFailureMessage(failure)});
    }
  }
  closeFileOpen() {
    ++this.operationGeneration; this.discardIntent(this.view.intent);
    this.publishView({phase:'idle', reference:'', messageIdentity:'', intent:null, error:''});
  }
  disposeFileOpening() {
    this.isDisposed = true; this.closeFileOpen(); this.listeners.clear();
  }
}
