import test from 'node:test';
import assert from 'node:assert/strict';
import {focusValidationIssue,normalizeValidationIssues,validationPathKey,validationIssueLabel,validateModelsSettings,validateMcpSettings} from '../src/settingsValidation.ts';

test('校验路径保留数组下标，格式无效的问题不会进入字段定位',()=>{
  const issue={domain:'execution',path:['command_profiles',2,'name'],message:'请填写名称。'};
  assert.deepEqual(normalizeValidationIssues([issue,{domain:'x',path:[{}],message:'bad'},null]),[issue]);
  assert.equal(validationPathKey(issue.domain,issue.path),'["execution","command_profiles",2,"name"]');
  assert.equal(validationIssueLabel(issue),'执行与进程 · 命令资源配置 · 第 3 项 · 名称');
  assert.equal(validationIssueLabel({domain:'models',path:['providers','p','models','m','base_url'],message:'bad'}),'供应商 p · 模型 m · Base URL');
  assert.equal(validationIssueLabel({domain:'mcp',path:['server','command'],message:'bad'}),'MCP server · 启动命令');
});

test('模型目录聚合校验覆盖隐藏模型和不存在的默认引用，错误不包含密钥值',()=>{
  const config={providers:{p:{name:'test',protocol:'openai',base_url:'https://example.invalid/v1',api_key:'private-secret',models:{one:{model_name:'one'},two:{model_name:''}}}},default_model:'p/missing'};
  const issues=validateModelsSettings(config);
  assert.deepEqual(issues.map(issue=>issue.path),[['providers','p','models','two','model_name'],['default_model']]);
  assert.equal(JSON.stringify(issues).includes('private-secret'),false);
  config.providers.p.models.two.model_name='two';config.default_model='p/two';
  assert.deepEqual(validateModelsSettings(config),[]);
  assert.ok(validateModelsSettings({providers:{},default_model:''}).length);
});

test('MCP聚合校验按传输类型定位缺失连接，并允许空目录',()=>{
  assert.deepEqual(validateMcpSettings({}),[]);
  const issues=validateMcpSettings({stdio:{type:'stdio',command:''},http:{type:'http',url:'example.invalid'}});
  assert.deepEqual(issues.map(issue=>issue.path),[['stdio','command'],['http','url']]);
});

test('错误定位使用最长已渲染祖先，展开全部高级区并聚焦 JSON 编辑器',async()=>{
  const oldDocument=globalThis.document,oldRaf=globalThis.requestAnimationFrame;
  const calls=[],outer={tagName:'DETAILS',open:false,parentElement:null},inner={tagName:'DETAILS',open:false,parentElement:outer};
  const control={focus:options=>calls.push(['focus',options])};
  const field={dataset:{settingPath:validationPathKey('execution',['command_profiles'])},tagName:'DIV',parentElement:inner,
    querySelector:()=>control,scrollIntoView:options=>calls.push(['scroll',options])};
  globalThis.document={querySelectorAll:()=>[field]};globalThis.requestAnimationFrame=callback=>queueMicrotask(callback);
  try{
    assert.equal(await focusValidationIssue({domain:'execution',path:['command_profiles',2,'name'],message:'bad'}),true);
    assert.equal(inner.open,true);assert.equal(outer.open,true);assert.equal(calls[1][0],'focus');
  }finally{globalThis.document=oldDocument;globalThis.requestAnimationFrame=oldRaf;}
});

test('局部表单定位不会选中背景同路径字段，缺少目标时重试后返回失败',async()=>{
  const oldDocument=globalThis.document,oldRaf=globalThis.requestAnimationFrame;
  let globalQueries=0,localQueries=0,focused=0;
  const field={dataset:{settingPath:validationPathKey('models',['base_url'])},tagName:'DIV',parentElement:null,querySelector:()=>({focus:()=>focused++})};
  const root={hasAttribute:()=>false,querySelectorAll:()=>{localQueries++;return localQueries===1?[]:[field];}};
  globalThis.document={querySelectorAll:()=>{globalQueries++;throw new Error('background must remain untouched');}};
  globalThis.requestAnimationFrame=callback=>queueMicrotask(callback);
  try{
    assert.equal(await focusValidationIssue({domain:'models',path:['base_url'],message:'bad'},root),true);
    assert.equal(localQueries,2);assert.equal(globalQueries,0);assert.equal(focused,1);
    assert.equal(await focusValidationIssue({domain:'models',path:['missing'],message:'bad'},{hasAttribute:()=>false,querySelectorAll:()=>[]}),false);
  }finally{globalThis.document=oldDocument;globalThis.requestAnimationFrame=oldRaf;}
});
