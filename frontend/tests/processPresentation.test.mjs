import test from 'node:test';
import assert from 'node:assert/strict';
import {processState,groupProcesses,appendProcessOutput,emptyProcessPage} from '../src/processPresentation.ts';
import {effortOptions,EFFORT_LABELS} from '../src/reasoning.ts';

test('进程结束及停止中不再提供无效控制，未知状态默认没有控制',()=>{
  for(const status of ['completed','exited','failed','cancelled','interrupted','lost']){
    const state=processState({status});assert.equal(state.canStop,false);assert.equal(state.canWrite,false);assert.equal(state.canBackground,false);
  }
  const stopping=processState({status:'stopping'});assert.equal(stopping.active,true);assert.equal(stopping.canStop,false);assert.equal(stopping.canWrite,false);
  assert.equal(processState({status:'starting'}).canStop,true);
  assert.equal(processState({status:'starting'}).canBackground,false);
});
test('运行中进程可操作，已保留会话不再重复显示转后台',()=>{
  assert.equal(processState({status:'running',lifetime:'turn'}).canBackground,true);
  assert.equal(processState({status:'running',lifetime:'session'}).canBackground,false);
  assert.equal(processState({status:'running'}).canWrite,true);
  assert.equal(processState({status:'completed',exit_code:7}).failed,true);
});
test('活动进程不会被历史淹没，分组排序不修改原始快照',()=>{
  const rows=[{process_id:'old',status:'completed',updated_at:'2026-10-01'}, {process_id:'live',status:'running'}, {process_id:'new',status:'failed',updated_at:'2026-10-13'}, {process_id:'starting',status:'starting'}];
  const copy=structuredClone(rows);const groups=groupProcesses(rows);
  assert.deepEqual(groups.active.map(row=>row.process_id),['live','starting']);assert.deepEqual(groups.finished.map(row=>row.process_id),['new','old']);assert.deepEqual(rows,copy);
});
test('日志按独立游标追加，翻页不丢 stdin 草稿和未读取标志',()=>{
  const first=appendProcessOutput({...emptyProcessPage(),input:'尚未发送'},{text:'first\n',next_cursor:6,truncated:true});
  assert.equal(first.more,true);assert.equal(first.cursor,6);
  const second=appendProcessOutput(first,{output:{text:'second',next_cursor:12,truncated:false}});
  assert.equal(second.output,'first\nsecond');assert.equal(second.input,'尚未发送');assert.equal(second.more,false);assert.equal(second.loaded,true);
  assert.equal(first.output,'first\n');
});
test('长日志截断标记持续保留，绝不回退服务端字符游标',()=>{
  const page=appendProcessOutput(emptyProcessPage(),{text:'x'.repeat(210000),next_cursor:210000});
  assert.equal(page.output.length,200000);assert.equal(page.trimmed,true);assert.equal(page.cursor,210000);
  const next=appendProcessOutput(page,{text:'',next_cursor:210000});assert.equal(next.trimmed,true);
});
test('滑条只采用实际档位，低中高使用简短标签',()=>{
  assert.deepEqual(effortOptions({effort_levels:['low','high']}),['auto','low','high']);
  assert.deepEqual(effortOptions({effort_levels:[]}),['auto']);
  assert.equal(EFFORT_LABELS.low,'低');assert.equal(EFFORT_LABELS.medium,'中');assert.equal(EFFORT_LABELS.high,'高');
});
