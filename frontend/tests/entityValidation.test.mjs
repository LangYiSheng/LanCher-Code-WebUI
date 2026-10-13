import test from 'node:test';
import assert from 'node:assert/strict';
import {generateEntityId,isValidEntityId,isValidMcpName,isHttpUrl,validateProvider,validateProviderConnection,validateModel,validateMcp} from '../src/entityValidation.ts';

test('供应商和模型 ID 从实际名称生成，合法保留中文并避开重复',()=>{
  assert.equal(generateEntityId(' org/my.model ',['org-my-model','org-my-model-2']),'org-my-model-3');
  assert.equal(generateEntityId('我的 供应商',['我的-供应商']),'我的-供应商-2');
  assert.equal(generateEntityId('///',[],'provider'),'provider');
  assert.equal(isValidEntityId('模型_1-name'),true);assert.equal(isValidEntityId('org/model'),false);
  assert.equal(isValidMcpName('local-filesystem'),true);assert.equal(isValidMcpName('本地'),false);
});

test('连接字段校验指出协议 URL 和密钥，已有密钥留空保留',()=>{
  const value={name:'Demo',protocol:'',base_url:'ftp://example.com',api_key:''};
  assert.deepEqual(validateProviderConnection(value,['providers','demo']).map(issue=>issue.path),[['providers','demo','protocol'],['providers','demo','base_url'],['providers','demo','api_key']]);
  const valid={...value,protocol:'claude',base_url:'https://example.com',api_key_configured:true};
  assert.deepEqual(validateProviderConnection(valid),[]);
  assert.equal(validateProviderConnection(valid,[],'models',true).at(0).path.at(-1),'api_key');
  assert.equal(validateProviderConnection({...valid,api_key_clear:true}).at(0).path.at(-1),'api_key');
  assert.equal(JSON.stringify(validateProviderConnection({...value,api_key:'private-token'})).includes('private-token'),false);
  assert.equal(validateProvider({...valid,api_mode:null}).at(0).path.at(-1),'api_mode');
  assert.deepEqual(validateProvider(valid),[]);
});

test('实际模型名称可以包含斜杠，连接覆盖留空继承；无效数值可定位',()=>{
  assert.deepEqual(validateModel({model_name:'org/my.model',base_url:null,protocol:null,timeout_seconds:null,context_window:null}),[]);
  assert.deepEqual(validateModel({model_name:'',base_url:'not-url',context_window:0,max_output_tokens:1.5,timeout_seconds:Infinity}).map(issue=>issue.path.at(-1)),['model_name','base_url','timeout_seconds','context_window','max_output_tokens']);
});

test('MCP 区分传输类型的必填字段并验证有限正数超时',()=>{
  assert.deepEqual(validateMcp({type:'stdio',command:'npx',args:['-y'],env:{TOKEN:''},tool_timeout_seconds:60}),[]);
  assert.deepEqual(validateMcp({type:'http',url:'http://127.0.0.1:8080/mcp',headers:{TOKEN:''}}),[]);
  assert.deepEqual(validateMcp({type:'stdio',command:'',tool_timeout_seconds:0,startup_timeout_seconds:-1}).map(issue=>issue.path.at(-1)),['command','startup_timeout_seconds','tool_timeout_seconds']);
  assert.equal(validateMcp({type:'http',url:'file:///tmp/mcp'}).at(0).path.at(-1),'url');
  assert.equal(isHttpUrl('https://example.com/mcp'),true);assert.equal(isHttpUrl('https://example.com/a b'),false);
});

test('URL 不接受内嵌凭据查询或片段，供应商模板保留给服务端展开校验',()=>{
  for(const value of ['https://user:pass@example.com/v1','https://example.com/v1?token=private','https://example.com/v1#section'])assert.equal(isHttpUrl(value),false);
  assert.equal(isHttpUrl('https://example.com/v1'),true);
  assert.equal(isHttpUrl('${MODEL_BASE_URL}',true),true);
  assert.equal(isHttpUrl('https://${MODEL_HOST}/v1',true),true);
  assert.equal(isHttpUrl('$MODEL_BASE_URL',true),true);
  assert.deepEqual(validateProviderConnection({name:'Demo',protocol:'openai',base_url:'${MODEL_BASE_URL}',api_key_configured:true}),[]);
  assert.deepEqual(validateModel({model_name:'model',base_url:'${OVERRIDE_BASE_URL}'}),[]);
  assert.equal(validateMcp({type:'http',url:'${MCP_URL}'}).at(0).path.at(-1),'url');
  assert.deepEqual(validateMcp({type:'http',url:'https://example.com/mcp?workspace=demo#tools'}),[]);
  assert.equal(validateMcp({type:'http',url:'https://user:pass@example.com/mcp?workspace=demo'}).at(0).path.at(-1),'url');
});
