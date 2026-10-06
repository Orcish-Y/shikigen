import { useLayoutEffect, useRef, useState, type KeyboardEvent } from 'react';
import { MagnifyingGlass, Plus, SidebarSimple, ClockCounterClockwise, SlidersHorizontal, ChatCircle } from '@phosphor-icons/react';
import { listCommands, moveCommandSelection, resolveSelectedCommand, type CommandAction, type CommandPanelContext } from '../command-panel';
import { isCompositionKey, type CompositionState } from '../workspace-shortcuts';
import { Overlay } from './Overlay';

const commandIcons = {
  'create-conversation': Plus, 'toggle-navigation': SidebarSimple,
  'find-conversation': ClockCounterClockwise, 'run-details': SlidersHorizontal, 'select-conversation': ChatCircle,
};

export function CommandPanel({context, shortcut, onExecute, onClose}: {
  context: CommandPanelContext;
  shortcut: string;
  onExecute: (action: CommandAction) => void;
  onClose: () => void;
}) {
  const [query, setQuery] = useState('');
  const [selectionId, setSelectionId] = useState<string | null>(null);
  const composition = useRef<CompositionState>({isActive: false, endedAt: -Infinity});
  const results = useRef<HTMLDivElement>(null);
  const choices = listCommands(context, query);
  const selection = resolveSelectedCommand(choices, selectionId);
  const selectionIndex = choices.findIndex(choice => choice.id === selection?.id);
  useLayoutEffect(() => {
    results.current?.querySelector<HTMLElement>('[aria-selected=true]')?.scrollIntoView({block: 'nearest'});
  }, [selection?.id]);
  function selectWithKeyboard(event: KeyboardEvent<HTMLDivElement>) {
    if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey
      || isCompositionKey(event.nativeEvent, composition.current)) return;
    if (!['ArrowDown', 'ArrowUp', 'Enter'].includes(event.key)) return;
    // Native button Enter also must not activate repeatedly when held down.
    if (event.repeat) { event.preventDefault(); return; }
    if (event.key === 'Enter') {
      if (!(event.target instanceof HTMLInputElement)) return;
      event.preventDefault();
      if (selection) onExecute(selection.action);
    } else {
      event.preventDefault();
      setSelectionId(moveCommandSelection(choices, selection?.id ?? null, event.key === 'ArrowDown' ? 'next' : 'previous'));
      document.getElementById('command-search')?.focus();
    }
  }
  return <Overlay title="命令面板" initialFocus="#command-search"
    fallbackFocus=".app-bar [aria-label='打开命令面板'], .chat-workspace" onClose={onClose}>
    <div className="command-panel" onKeyDown={selectWithKeyboard}
      onCompositionStart={() => { composition.current.isActive = true; }}
      onCompositionEnd={event => { composition.current = {isActive: false, endedAt: event.timeStamp}; }}>
      <label className="command-search">
        <MagnifyingGlass size={16}/>
        <input id="command-search" role="combobox" aria-label="搜索操作和已加载会话"
          aria-controls="command-results" aria-expanded aria-autocomplete="list"
          aria-activedescendant={selectionIndex >= 0 ? `command-choice-${selectionIndex}` : undefined}
          placeholder="搜索操作和已加载会话…" value={query}
          onChange={event => { setQuery(event.target.value); setSelectionId(null); }}/>
      </label>
      <p className="command-scope">仅搜索操作名称和已加载会话标题</p>
      <div className="command-results" id="command-results" role="listbox" aria-label="命令选项" ref={results}>
        {(['actions', 'conversations'] as const).map(group => {
          const groupChoices = choices.filter(choice => choice.group === group);
          if (!groupChoices.length) return null;
          const groupLabel = group === 'actions' ? '操作' : '已加载会话';
          return <div role="group" aria-label={groupLabel} key={group}>
            <h3 className="command-group">{groupLabel}</h3>
            {groupChoices.map(choice => {
              const choiceIndex = choices.indexOf(choice);
              const ChoiceIcon = commandIcons[choice.action.kind];
              return <button id={`command-choice-${choiceIndex}`} key={choice.id} className="command-choice"
                role="option" aria-selected={choice.id === selection?.id} data-command-id={choice.id}
                disabled={choice.unavailableReason !== null} aria-disabled={choice.unavailableReason !== null}
                title={choice.unavailableReason ?? choice.label}
                onFocus={() => setSelectionId(choice.id)}
                onClick={() => { if (choice.unavailableReason === null) onExecute(choice.action); }}>
                <ChoiceIcon size={18}/>
                <span className="command-copy"><span className="command-label">{choice.label}</span>
                  {(choice.unavailableReason || choice.description) && <span className="command-description">
                    {choice.unavailableReason ?? choice.description}</span>}</span>
                {choice.shortcut && <kbd>{shortcut} {choice.shortcut}</kbd>}
              </button>;
            })}
          </div>;
        })}
        {!choices.length && <p className="command-empty" role="status">没有匹配的操作或已加载会话</p>}
      </div>
      <p className="command-help">↑ ↓ 选择 · Enter 执行 · Esc 关闭</p>
    </div>
  </Overlay>;
}
