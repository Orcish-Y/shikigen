export type CommandAction =
  | {kind: 'create-conversation' | 'toggle-navigation' | 'find-conversation' | 'run-details'}
  | {kind: 'select-conversation'; conversationId: string};

export interface CommandChoice {
  id: string;
  group: 'actions' | 'conversations';
  label: string;
  description?: string;
  unavailableReason: string | null;
  shortcut?: 'N' | 'B';
  action: CommandAction;
}

export interface CommandPanelContext {
  conversations: readonly {id: string; title: string; status?: string; summary: string}[];
  isDesktop: boolean;
  isNavigationCollapsed: boolean;
  createUnavailableReason: string | null;
  detailsUnavailableReason: string | null;
}

/** This projection only receives already loaded titles; it never reads history. */
export function listCommands(context: CommandPanelContext, query: string): CommandChoice[] {
  const choices: CommandChoice[] = [
    {id: 'create-conversation', group: 'actions', label: '新建会话', shortcut: 'N',
      unavailableReason: context.createUnavailableReason, action: {kind: 'create-conversation'}},
    {id: 'toggle-navigation', group: 'actions', label: context.isDesktop
      ? `${context.isNavigationCollapsed ? '展开' : '收起'}主导航` : '打开主导航', shortcut: 'B',
      unavailableReason: null, action: {kind: 'toggle-navigation'}},
    {id: 'find-conversation', group: 'actions', label: '查找会话',
      unavailableReason: null, action: {kind: 'find-conversation'}},
    {id: 'run-details', group: 'actions', label: '查看运行详情',
      unavailableReason: context.detailsUnavailableReason, action: {kind: 'run-details'}},
    ...context.conversations.map(conversation => ({
      id: `conversation:${conversation.id}`, group: 'conversations' as const, label: conversation.title,
      description: [conversation.status, conversation.summary].filter(Boolean).join(' · '),
      unavailableReason: null, action: {kind: 'select-conversation' as const, conversationId: conversation.id},
    })),
  ];
  const normalizedQuery = query.trim().toLocaleLowerCase();
  return choices.filter(choice => choice.label.toLocaleLowerCase().includes(normalizedQuery));
}

export function resolveSelectedCommand(choices: readonly CommandChoice[], selectionId: string | null): CommandChoice | null {
  return choices.find(choice => choice.id === selectionId && choice.unavailableReason === null)
    ?? choices.find(choice => choice.unavailableReason === null) ?? null;
}

export function moveCommandSelection(choices: readonly CommandChoice[], selectionId: string | null,
  direction: 'next' | 'previous'): string | null {
  const availableChoices = choices.filter(choice => choice.unavailableReason === null);
  if (!availableChoices.length) return null;
  const currentIndex = availableChoices.findIndex(choice => choice.id === selectionId);
  if (currentIndex < 0) return (direction === 'next' ? availableChoices[0] : availableChoices.at(-1))!.id;
  const offset = direction === 'next' ? 1 : -1;
  return availableChoices[(currentIndex + offset + availableChoices.length) % availableChoices.length].id;
}
