import test from 'node:test';
import assert from 'node:assert/strict';
import {messagePresentation,thinkingDuration,appendMessageText} from '../src/messagePresentation.ts';

const message=(overrides={})=>({id:'m',role:'assistant',status:'complete',content:'进度最终回答',timestamp:'2026-10-13T01:00:00Z',completed_at:'2026-10-13T01:02:03Z',trace:{entries:[
  {kind:'thinking',text:'分析'}, {kind:'text',text:'进度'},
  {kind:'tool_call',call_id:'a'}, {kind:'tool_result',call_id:'a',text:'工具输出'},
  {kind:'thinking',text:'整理结果'}, {kind:'text',text:'最终回答'},
]},...overrides});

test('每轮只复制并展示最后正文，过程按原序保留且不改写历史',()=>{
  const source=message(),before=structuredClone(source),view=messagePresentation(source);
  assert.equal(view.answer,'最终回答');assert.equal(view.process.length,5);
  assert.deepEqual(view.process,source.trace.entries.slice(0,-1));assert.deepEqual(source,before);
});
test('流式过程完整可见，结束前不提供复制最终回答',()=>{
  const source=message({status:'streaming'}),view=messagePresentation(source);
  assert.equal(view.answer,'');assert.deepEqual(view.process,source.trace.entries);assert.equal(view.streaming,true);
});
test('只有一段正文时无需生成空思考折叠区',()=>{
  const view=messagePresentation(message({trace:{entries:[{kind:'text',text:'直接回答'}]}}));
  assert.equal(view.answer,'直接回答');assert.equal(view.process.length,0);
});
test('纯正文历史和用户消息保持原文，包括 Markdown 和换行',()=>{
  const content='## 结果\n\n```py\nprint(1)\n```';
  assert.equal(messagePresentation(message({trace:undefined,content})).answer,content);
  assert.equal(messagePresentation(message({role:'user',content})).answer,content);
});
test('工具后中断时不能把进度文字冒充最终回答',()=>{
  const source=message({status:'cancelled'});source.trace.entries.splice(4);
  assert.equal(messagePresentation(source).answer,'');
});
test('错误提示只展示一次，部分输出仍可复制',()=>{
  const source=message({status:'error'});source.trace.entries.push({kind:'notice',text:'连接中断',metadata:{severity:'error'}});
  const view=messagePresentation(source);assert.equal(view.answer,'最终回答');assert.equal(view.notices.length,1);
  assert.ok(!view.process.includes(view.notices[0]));
  const empty=messagePresentation(message({status:'error',content:'连接中断',trace:{entries:view.notices}}));
  assert.equal(empty.answer,'');assert.equal(empty.notices.length,1);
});
test('已经恢复的续写提示收进过程，不重复干扰最终回答',()=>{
  const source=message();source.trace.entries.splice(4,0,{kind:'notice',text:'自动续接',metadata:{severity:'warning'}});
  const view=messagePresentation(source);assert.equal(view.notices.length,0);assert.equal(view.process.length,6);
});
test('耗时在完成后固定，缺失或异常时间不伪造数值',()=>{
  assert.equal(thinkingDuration(message(),Date.parse('2026-10-14T00:00:00Z')),'2分03秒');
  assert.equal(thinkingDuration(message({status:'streaming'}),Date.parse('2026-10-13T01:00:09Z')),'9秒');
  assert.equal(thinkingDuration(message({completed_at:undefined})),'');
  assert.equal(thinkingDuration(message({completed_at:'bad'})),'');
  assert.equal(thinkingDuration(message({timestamp:'2026-10-15T00:00:00Z'})),'');
});
test('正文增量只延续当前流式段，不跨工具段且不污染原快照',()=>{
  const source=message({status:'streaming',content:'',trace:{entries:[{kind:'text',text:'进度',metadata:{state:'complete'}},{kind:'tool_result',call_id:'a'}]}});
  const first=appendMessageText(source,'最终'),next=appendMessageText(first,'回答');
  assert.equal(next.trace.entries[2].text,'最终回答');assert.equal(next.content,'最终回答');
  assert.equal(source.trace.entries.length,2);assert.equal(first.trace.entries[2].text,'最终');
});
test('无轨迹的旧流式快照补上轨迹时不会丢掉已有正文',()=>{
  const next=appendMessageText(message({trace:undefined,content:'已有',status:'streaming'}),'新增');
  assert.equal(next.trace.entries[0].text,'已有新增');
});
