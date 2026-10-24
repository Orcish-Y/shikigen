import { useImperativeHandle, useRef, useState, type Ref } from 'react';
import type { BackendSession } from '../../backend-client';
import type { ContentView } from '../MessageBody';
import { ToolsWorkspace, type ToolsWorkspaceHandle, type ToolEditorHandle } from './ToolsWorkspace';
import { McpWorkspace, type McpWorkspaceHandle } from './McpWorkspace';

import type { ExtensionCategory, ToolLibrarySnapshot, McpLibrarySnapshot } from '../../extension-library';
import { ExtensionLibrarySidebar } from './ExtensionLibrarySidebar';

type EditorKind = 'tools' | 'mcp';

/** Keep the existing editors and their leave guards, sharing one library column. */
export function ExtensionsWorkspace({session, onView, ref}: {
  session: BackendSession | null;
  onView: (view: ContentView) => void;
  ref?: Ref<ToolsWorkspaceHandle>;
}) {
  const [category, setCategory] = useState<ExtensionCategory>('all');
  const [activeEditor, setActiveEditor] = useState<EditorKind>('tools');
  const activeEditorKind = useRef<EditorKind>('tools');
  const [toolLibrary, setToolLibrary] = useState<ToolLibrarySnapshot | null>(null);
  const [mcpLibrary, setMcpLibrary] = useState<McpLibrarySnapshot | null>(null);
  const toolsRef = useRef<ToolEditorHandle>(null);
  const mcpRef = useRef<McpWorkspaceHandle>(null);
  const [toolId, setToolId] = useState<string>();
  const [connectionId, setConnectionId] = useState<string>();
  function requestLeave(action: () => void) {
    if (category === 'skill') {action();return;}
    const editor = activeEditor === 'tools' ? toolsRef.current : mcpRef.current;
    if (editor) editor.requestLeave(action); else action();
  }
  useImperativeHandle(ref, () => ({requestLeave}));

  // Reset only the outgoing editor after its leave guard approves. The library
  // stays mounted, retaining counts and rows while the next view refreshes.
  function activateEditor(kind: EditorKind, action?: () => void) {
    const previousKind = activeEditorKind.current;
    if (kind !== previousKind) {
      if (previousKind === 'tools') toolsRef.current?.resetEditor();
      else mcpRef.current?.resetEditor();
      if (previousKind === 'tools') setToolId(undefined); else setConnectionId(undefined);
      activeEditorKind.current = kind;
      setActiveEditor(kind);
      if (!action) {
        if (kind === 'tools') toolsRef.current?.reloadLibrary(true);
        else mcpRef.current?.reloadLibrary(true);
      }
    }
    action?.();
  }
  function switchCategory(next: ExtensionCategory) {
    if (next === category) return;
    // Filtering the current editor does not leave it or discard its draft.
    if (next === 'all' || next === activeEditor) {setCategory(next);return;}
    requestLeave(() => {
      setCategory(next);
      if (next === 'tools' || next === 'mcp') activateEditor(next);
      else if (next === 'skill') {
        toolsRef.current?.resetEditor();mcpRef.current?.resetEditor();
        setToolId(undefined);setConnectionId(undefined);
      }
    });
  }
  function openMcp(nextId?: string) {
    activateEditor('mcp');setConnectionId(nextId);
    if (category !== 'all') setCategory('mcp');
  }
  function openTool(nextId: string) {
    activateEditor('tools');setToolId(nextId);
    if (category !== 'all') setCategory('tools');
  }

  return <div className="extensions-workspace">
    <ExtensionLibrarySidebar category={category} onCategory={switchCategory} toolLibrary={toolLibrary}
      mcpLibrary={mcpLibrary} connected={Boolean(session)} activeEditor={activeEditor}
      onCreateTool={kind => toolsRef.current?.createTool(kind)} onImportOpenApi={() => toolsRef.current?.importOpenApi()}
      onCreateMcp={transport => mcpRef.current?.createConnection(transport)}
      onOpenTool={tool => toolsRef.current?.openTool(tool)} onOpenMcp={connectionId => mcpRef.current?.openConnection(connectionId)}
      onReload={() => {
        if (toolLibrary?.canReload) toolsRef.current?.reloadLibrary();
        if (mcpLibrary?.canReload) mcpRef.current?.reloadLibrary();
      }}/>
    <div className="extensions-detail">
      <div className="extensions-editor" hidden={category === 'skill' || activeEditor !== 'tools'}>
        <ToolsWorkspace ref={toolsRef} session={session} onView={onView}
          hideSidebar onLibrarySnapshot={setToolLibrary} initialToolId={toolId} onOpenMcp={openMcp}
          onActivate={activeEditor === 'tools' && category !== 'skill' ? undefined : action => requestLeave(() => {
            if (category !== 'all') setCategory('tools');
            activateEditor('tools', action);
          })}/>
      </div>
      <div className="extensions-editor" hidden={category === 'skill' || activeEditor !== 'mcp'}>
        <McpWorkspace ref={mcpRef} session={session} initialConnectionId={connectionId}
          hideSidebar onLibrarySnapshot={setMcpLibrary} onOpenTool={openTool}
          onActivate={activeEditor === 'mcp' && category !== 'skill' ? undefined : action => requestLeave(() => {
            if (category !== 'all') setCategory('mcp');
            activateEditor('mcp', action);
          })}/>
      </div>
      {category === 'skill' && <section className="tool-detail-empty" aria-label="Skill"><h1>Skill</h1><p>技能管理暂未开放。</p></section>}
    </div>
  </div>;
}
