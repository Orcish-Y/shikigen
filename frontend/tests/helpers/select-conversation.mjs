/** 历史会话专项测试显式模拟用户点击；生产启动保持新会话欢迎页。 */
export function selectConversationWhenListed(store, threadId) {
  let unsubscribe = () => {};
  const selectListedConversation = () => {
    const snapshot = store.getSnapshot();
    const targetId = threadId ?? snapshot.threads[0]?.id;
    if (snapshot.activeId) {unsubscribe(); return;}
    if (!snapshot.threads.some(thread => thread.id === targetId)) return;
    unsubscribe();
    store.select(targetId);
  };
  unsubscribe = store.subscribe(selectListedConversation);
  selectListedConversation();
}
