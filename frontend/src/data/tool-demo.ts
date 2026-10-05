import type { MessageContent, StoredMessage } from '../backend-client';
import { presentMessage } from '../message-presentation';

// 浏览器预览专用公开消息形状。没有后端运行，也不会执行这些工具。
const content = (seq:number, value:MessageContent):StoredMessage => ({
  id:seq, thread_id:'demo-tools', run_id:'demo-tools-run', run_status:'completed', seq,
  category:'message', event_type:'created', event_key:null, metadata:{example:true},
  created_at:'2026-10-05T00:00:00Z', content:value,
});
const calls = ['first', 'second', 'failed', 'waiting', 'ambiguous', 'ambiguous', 'duplicate']
  .map(id => ({id, name:'read_file', args:{path:`reports/${id}.txt`, options:{lines:0, full:true}}}));
const records = [content(1, {type:'human', message_id:'tool-user', content:'演示工具完整记录：同名调用、乱序结果、失败、空值和未配对结果。'}),
  content(2, {type:'ai', message_id:'tool-agent', content:'以下为工具卡片的**界面示例**。状态依据示例工具消息，不会执行工具。', tool_calls:calls}),
  content(3, {type:'tool', message_id:'second-result', tool_call_id:'second', name:'read_file', status:'success', content:'Error 字样不改变 success 状态。', artifact:0}),
  content(4, {type:'tool', message_id:'first-result', tool_call_id:'first', name:'returned_name', status:'success', content:'', artifact:''}),
  content(5, {type:'tool', message_id:'failed-result', tool_call_id:'failed', name:'read_file', status:'error', content:'  工具未能读取文件。\n参数与附加数据仍默认折叠。\n', artifact:{details:[false, 0, null], path:'reports/error.json'}}),
  content(6, {type:'tool', message_id:'ambiguous-result', tool_call_id:'ambiguous', name:'read_file', status:'success', content:[], artifact:false}),
  content(7, {type:'tool', message_id:'duplicate-one', tool_call_id:'duplicate', name:'read_file', status:'success', content:'重复结果一', artifact:[]}),
  content(8, {type:'tool', message_id:'duplicate-two', tool_call_id:'duplicate', name:'read_file', status:'error', content:'重复结果二', artifact:{}}),
  content(9, {type:'tool', message_id:'orphan-result', tool_call_id:'unmatched', name:'actual_name', status:'success', content:[{type:'custom', text:'未知结构保留 JSON', extra:[0, false]}], artifact:null}),
];
export const toolDemoMessages = records.map(presentMessage);
