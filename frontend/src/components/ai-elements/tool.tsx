// Adapted from Vercel AI Elements, Apache-2.0, Copyright 2023 Vercel, Inc.
// Source: 6a9d5b1822ffb10bba4bd97175f01edd7d8651cd/packages/elements/src/tool.tsx.
// Local adaptation uses product test states and explicit JSON values; no AI SDK transport.
import { CaretDown, CheckCircle, Clock, Wrench, XCircle } from '@phosphor-icons/react';
import type { ComponentProps } from 'react';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '../ui/collapsible';
import { isToolTestActive, toolTestStatus, type ToolTest } from '../../tool-library';

export function Tool(props: ComponentProps<typeof Collapsible>) {
  return <Collapsible className="tool-test-result" {...props}/>;
}
export function ToolHeader({status}: {status: ToolTest['status']}) {
  const Icon = isToolTestActive(status) ? Clock : status === 'success' ? CheckCircle : XCircle;
  return <CollapsibleTrigger className="tool-test-heading">
    <Wrench size={16}/><span>工具测试结果</span>
    <span className={`tool-test-status ${status}`}><Icon size={16}/>{toolTestStatus(status)}</span><CaretDown size={16}/>
  </CollapsibleTrigger>;
}
export function ToolContent(props: ComponentProps<typeof CollapsibleContent>) {
  return <CollapsibleContent className="tool-test-content" {...props}/>;
}
export function ToolOutput({value}: {value: unknown}) {
  return <pre aria-label="工具返回 data">{JSON.stringify(value, null, 2)}</pre>;
}
