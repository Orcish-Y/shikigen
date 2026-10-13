// Adapted from Vercel AI Elements, Apache-2.0, Copyright 2023 Vercel, Inc.
// Source: 6a9d5b1822ffb10bba4bd97175f01edd7d8651cd/packages/elements/src/reasoning.tsx.
// Local changes and license copies: frontend/component-libraries.md.
import { useControllableState } from '@radix-ui/react-use-controllable-state';
import { Brain, CaretDown } from '@phosphor-icons/react';
import { createContext, memo, useCallback, useContext, useMemo, type ComponentProps, type ReactNode } from 'react';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import { cn } from '@/lib/utils';

interface ReasoningContextValue {
  isStreaming: boolean;
  isOpen: boolean;
  setIsOpen: (isOpen: boolean) => void;
  duration: number | undefined;
}

const ReasoningContext = createContext<ReasoningContextValue | null>(null);

export const useReasoning = () => {
  const context = useContext(ReasoningContext);
  if (!context) throw new Error('Reasoning components must be used within Reasoning');
  return context;
};

export type ReasoningProps = ComponentProps<typeof Collapsible> & {
  isStreaming?: boolean;
  duration?: number;
};

export const Reasoning = memo(({
  className, isStreaming = false, open, defaultOpen = true, onOpenChange, duration,
  children, ...props
}: ReasoningProps) => {
  const [isOpen, setIsOpen] = useControllableState<boolean>({
    defaultProp: defaultOpen, onChange: onOpenChange, prop: open,
  });
  // Streaming describes content only. It must never change the user's fold choice
  // or invent a model reasoning duration from local presentation time.
  const onExpansionChange = useCallback((nextIsOpen: boolean) => {
    setIsOpen(nextIsOpen);
  }, [setIsOpen]);
  const contextValue = useMemo(() => ({duration, isOpen, isStreaming, setIsOpen}),
    [duration, isOpen, isStreaming, setIsOpen]);
  return <ReasoningContext.Provider value={contextValue}>
    <Collapsible className={cn(className)} onOpenChange={onExpansionChange} open={isOpen} {...props}>
      {children}
    </Collapsible>
  </ReasoningContext.Provider>;
});

export type ReasoningTriggerProps = ComponentProps<typeof CollapsibleTrigger> & {
  getThinkingMessage?: (isStreaming: boolean, duration?: number) => ReactNode;
};

const getThinkingMessage = (isStreaming: boolean, duration?: number) =>
  isStreaming ? '生成中' : duration === undefined ? '思考内容' : `思考用时 ${duration} 秒`;

export const ReasoningTrigger = memo(({
  className, children, getThinkingMessage: renderThinkingMessage = getThinkingMessage, ...props
}: ReasoningTriggerProps) => {
  const {isStreaming, isOpen, duration} = useReasoning();
  return <CollapsibleTrigger className={cn(className)} {...props}>
    {children ?? <>
      <Brain size={16} aria-hidden="true" />
      {renderThinkingMessage(isStreaming, duration)}
      <CaretDown size={16} aria-hidden="true" className={cn(isOpen && 'rotate-180')} />
    </>}
  </CollapsibleTrigger>;
});

export type ReasoningContentProps = ComponentProps<typeof CollapsibleContent> & {
  children: ReactNode;
};

export const ReasoningContent = memo(({className, children, ...props}: ReasoningContentProps) => {
  const {isOpen} = useReasoning();
  // Preserve child identities (raw details, copy feedback, resource dialogs) while
  // folded. Explicit hidden is needed because Radix forceMount itself keeps open.
  return <CollapsibleContent className={cn(className)} {...props} forceMount hidden={!isOpen}>
    {children}
  </CollapsibleContent>;
});

Reasoning.displayName = 'Reasoning';
ReasoningTrigger.displayName = 'ReasoningTrigger';
ReasoningContent.displayName = 'ReasoningContent';
