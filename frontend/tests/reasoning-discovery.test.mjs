import test from 'node:test';
import assert from 'node:assert/strict';
import {effortOptions,capabilityList} from '../src/reasoning.ts';
import {discoveryEligible,preserveDiscoverySecrets} from '../src/discovery.ts';

test('推理选项只采用当前连接的核心档位，未知加载态与明确无档位仅auto',()=>{
  assert.deepEqual(effortOptions(undefined),['auto']);
  assert.deepEqual(effortOptions({effort_levels:['auto']}),['auto']);
  assert.deepEqual(effortOptions({effort_levels:['auto','low','high','high','ultra','off','none','disabled']}),['auto','low','high','ultra']);
});
test('端点未声明的档位由核心给出，而能力null与明确空声明分别显示',()=>{
  assert.deepEqual(effortOptions({effort_known:false,effort_levels:['auto','low','medium','high','xhigh','max']}),['auto','low','medium','high','xhigh','max']);
  assert.equal(capabilityList(null,'无手动档位'),'未声明');assert.equal(capabilityList([],'无手动档位'),'无手动档位');
});
test('发现全选覆盖所有可加入模型，已经加入的API名称不重复加入',()=>{
  assert.deepEqual(discoveryEligible({models:[{id:'one'},{id:'two'},{id:'three'}],existing:['one']}),['two','three']);
});
test('脱敏合并保留未保存的供应商和独立模型密钥，采用新能力快照',()=>{
  const before={api_key:'new-provider-fixture',api_key_clear:false,models:{one:{api_key:'new-model-fixture',api_key_clear:false,metadata:{fetched_at:'old'}}}};
  const merged={api_key:'',api_key_configured:true,models:{one:{api_key:'',api_key_configured:true,metadata:{fetched_at:'new'}},two:{api_key:null,metadata:{fetched_at:'new'}}}};
  const result=preserveDiscoverySecrets(before,merged);
  assert.equal(result.api_key,before.api_key);assert.equal(result.models.one.api_key,before.models.one.api_key);
  assert.equal(result.models.one.metadata.fetched_at,'new');assert.equal(result.models.two.api_key,null);
  assert.equal(merged.api_key,'');assert.equal(merged.models.one.api_key,'');
});
test('明确清除或恢复继承的密钥意图不会被合并返回值覆盖',()=>{
  const result=preserveDiscoverySecrets({api_key:'',api_key_clear:true,models:{one:{api_key:null,api_key_clear:true}}},{api_key:'',models:{one:{api_key:'',metadata:{id:'one'}}}});
  assert.equal(result.api_key_clear,true);assert.equal(result.models.one.api_key_clear,true);assert.equal(result.models.one.api_key,null);
});
