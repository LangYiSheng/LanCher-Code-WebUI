import test from 'node:test';
import assert from 'node:assert/strict';
import {chooseOnlyModel,initialSetupPage,issueStep,setupRequired,setupSteps} from '../src/setupState.ts';

test('全新安装展示介绍，已有配置缺模型和已看过介绍直接补配置',()=>{
  assert.equal(initialSetupPage({config_exists:false,state:'required'},false),'welcome');
  assert.equal(initialSetupPage({config_exists:true,state:'required'},false),'source');
  assert.equal(initialSetupPage({config_exists:true,state:'repair'},false),'source');
  assert.equal(initialSetupPage({config_exists:false,state:'required'},true),'source');
  assert.equal(initialSetupPage({state:'unreadable'},false),'source');
});

test('首次设置根据配置状态阻挡，在线接口状态不参与判断',()=>{
  assert.equal(setupRequired({state:'required'},[]),true);
  assert.equal(setupRequired({state:'repair'},[{id:'p/m'}]),true);
  assert.equal(setupRequired({state:'unreadable'},[]),true);
  assert.equal(setupRequired({state:'ready'},[{id:'p/m'}]),false);
  assert.equal(setupRequired({state:'ready'},[]),true);
  assert.equal(setupRequired({state:'ready'},[{id:'p/m'}],'配置读取失败'),true);
  assert.equal(setupRequired(undefined,[]),true);
});
test('修复步骤只增加出现问题的主配置领域',()=>{
  const issues=[{domain:'runtime',path:['work_phase'],message:'无效'},{domain:'execution',path:['limits','max_processes'],message:'无效'},{domain:'mcp',path:['x','command'],message:'无效'}];
  assert.deepEqual(setupSteps(issues),['connection','models','runtime','execution','review']);
  assert.equal(issueStep({domain:'models',path:['providers','p','api_key']}),'connection');
  assert.equal(issueStep({domain:'models',path:['providers','p','models','m','model_name']}),'models');
  assert.equal(issueStep({domain:'models',path:['providers','models','base_url']}),'connection');
  assert.equal(issueStep({domain:'models',path:['default_model']}),'review');
});
test('只有一个模型时自动设默认，多个模型保留明确选择',()=>{
  const one={providers:{p:{models:{m:{model_name:'api/model'}}}},default_model:''};
  assert.equal(chooseOnlyModel(one).default_model,'p/m');
  assert.equal(one.default_model,'');
  const several={providers:{p:{models:{a:{},b:{}}}},default_model:'p/b'};
  assert.equal(chooseOnlyModel(several),several);
});
test('坏字段仍保留原值，但模型选择标签不会渲染对象',()=>{
  const invalid={providers:{p:{name:{bad:true},models:{m:{model_name:{bad:true},display_name:{bad:true}}}}},default_model:''};
  assert.equal(chooseOnlyModel(invalid).default_model,'p/m');
  assert.deepEqual(invalid.providers.p.name,{bad:true});
});
