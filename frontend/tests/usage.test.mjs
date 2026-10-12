import test from 'node:test';
import assert from 'node:assert/strict';
import {contextSummary,usageSummary} from '../src/usage.ts';

test('嵌套未知总量不能由顶层零小计代替',()=>{const summary=usageSummary({answer:{input_tokens:0,output_tokens:0,cached_input_tokens:0,request_count:0,usage:{input_tokens:null,output_tokens:null,cached_input_tokens:null}}},'answer');assert.equal(summary.tokens.input_tokens,null);assert.equal(summary.total,null);assert.equal(summary.state,'empty');assert.equal(summary.knownSubtotal('input_tokens'),null);});
test('部分上报只展示已知小计，命中率保持后端未知',()=>{const summary=usageSummary({session:{input_tokens:15,output_tokens:20,request_count:2,cache_hit_ratio:null,usage:{input_tokens:null,output_tokens:20,cached_input_tokens:5,partial_fields:['input']}}},'session');assert.equal(summary.tokens.input_tokens,null);assert.equal(summary.knownSubtotal('input_tokens'),15);assert.equal(summary.total,20);assert.equal(summary.totalPartial,true);assert.equal(summary.cacheHitRatio,null);assert.deepEqual(summary.partial,['input']);});
test('总量不重复加入缓存、缓存创建和推理子项',()=>{const summary=usageSummary({project:{request_count:1,usage:{input_tokens:100,output_tokens:20,cached_input_tokens:80,cache_creation_input_tokens:10,reasoning_output_tokens:15}}},'project');assert.equal(summary.total,120);assert.equal(summary.state,'complete');});
test('释放或无效上下文没有虚假的零占比',()=>{assert.equal(contextSummary({}).ratio,null);assert.equal(contextSummary({tokens:3,window:0}).ratio,null);assert.equal(contextSummary({tokens:NaN,window:128000}).percent,null);assert.equal(contextSummary({tokens:-1,window:128000}).ratio,null);});
test('上下文保留真实占用和快照校准来源',()=>{const summary=contextSummary({tokens:150,window:100,source:'usage_calibrated'});assert.equal(summary.ratio,1.5);assert.equal(summary.percent,150);assert.equal(summary.source,'提供方校准估算');assert.equal(contextSummary({tokens:0,window:100,source:'estimated',snapshot:true}).source,'会话快照估算');assert.equal(contextSummary({tokens:0,window:100}).percent,0);});

test('嵌套部分数值与总量明确为已知小计',()=>{const summary=usageSummary({answer:{request_count:2,usage:{input_tokens:400,output_tokens:71,cached_input_tokens:0,cache_creation_input_tokens:0,reasoning_output_tokens:0,partial_fields:['input','output']}}},'answer');assert.equal(summary.tokens.input_tokens,400);assert.equal(summary.knownSubtotal('input_tokens'),400);assert.equal(summary.total,471);assert.equal(summary.totalPartial,true);assert.equal(summary.state,'partial');});
test('取消或EOF后的非最终上报不能成为完整用量',()=>{const summary=usageSummary({answer:{request_count:1,incomplete_request_count:1,usage:{input_tokens:10,output_tokens:2,cached_input_tokens:0,cache_creation_input_tokens:0,reasoning_output_tokens:0,is_final:false}}},'answer');assert.equal(summary.state,'incomplete');assert.equal(summary.quality,'上报未完成');assert.equal(summary.totalPartial,true);});

test('仅输出已知仍保留已知小计，输入输出均未知才隐藏总量',()=>{
  const only=usageSummary({session:{request_count:1,usage:{input_tokens:null,output_tokens:11}}},'session');
  assert.equal(only.total,11);assert.equal(only.totalPartial,true);
  assert.equal(usageSummary({session:{request_count:1,usage:{input_tokens:null,output_tokens:null,cached_input_tokens:4}}},'session').total,null);
});
test('不完整请求的缓存率保留SDK估算与样本数，前端不重算比率',()=>{
  const summary=usageSummary({session:{request_count:4,incomplete_request_count:2,invalid_request_count:1,cache_hit_ratio:.6,cache_ratio_estimated:true,cache_ratio_request_count:2,usage:{input_tokens:1000,cached_input_tokens:10,output_tokens:20,partial_fields:['input']}}},'session');
  assert.equal(summary.cacheHitRatio,.6);assert.equal(summary.cacheRatioEstimated,true);assert.equal(summary.cacheRatioRequestCount,2);assert.equal(summary.cacheRatioText,'≈60.0%');assert.match(summary.cacheRatioNote,/2 \/ 4/);assert.equal(summary.totalPartial,true);
});
