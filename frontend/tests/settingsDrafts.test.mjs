import test from 'node:test';
import assert from 'node:assert/strict';
import {SettingsDraftStore,SettingsDraftConflictError,settingsDraftId} from '../src/settingsDrafts.ts';

const key=(domain,scope='global',projectId)=>({domain,scope,...(projectId?{projectId}:{})});
function snapshot(revision='global-1'){
  return {revision,configured:true,preferences:{theme:'light',reduce_motion:false,reduce_transparency:false},
    config:{providers:{p:{name:'provider',protocol:'openai',base_url:'http://fixture.invalid/v1',api_key:'',api_key_configured:true,
      models:{one:{model_name:'one',display_name:'One',api_key:null,api_key_configured:false,api_mode:null,metadata:null,extension_configured:'keep-unknown'}}}},
      default_model:'p/one',ui:{show_timestamps:false,theme:'dark'},runtime:{tool_loop_limit:50},execution:{limits:{max_processes:20}}},
    global_mcp:{global:{command:'global-command',env:{TOKEN:''},env_configured:{TOKEN:true},headers:{}}},
    project_mcp:{project:{command:'project-command',env:{},headers:{}}},
    user_rules:[{match:'global-rule',result:'deny',scope:'user'}],
    project_rules:[{match:'project-rule',result:'deny',scope:'project'}]};
}
function store(){
  const drafts=new SettingsDraftStore();drafts.receive(snapshot());drafts.receive(snapshot('project-a-1'),'a');drafts.receive(snapshot('project-b-1'),'b');return drafts;
}

test('全局与项目来源分离，全局域不随工作项目另造草稿',()=>{
  const drafts=store(),global=key('models');
  drafts.edit(global,value=>({...value,default_model:'p/changed'}));
  const project=snapshot('project-a-2');project.config.default_model='p/from-project-source';
  drafts.receive(project,'a');
  assert.equal(drafts.get(key('models','global','a')),drafts.get(key('models','global','b')));
  assert.equal(drafts.get(global).value.default_model,'p/changed');
  assert.equal(drafts.get(global).revision,'global-1');assert.equal(drafts.get(global).conflict,false);
  assert.equal(drafts.getSession().revision,'global-1');assert.equal(drafts.getSession('a').revision,'project-a-2');
  assert.equal(settingsDraftId(key('rules','global')),settingsDraftId(key('rules','user')));
});

test('模型、UI、Agent、MCP与两项目规则的未保存编辑互不覆盖',()=>{
  const drafts=store();
  const edits=[[key('models'),value=>({...value,default_model:'p/local'})],
    [key('ui'),value=>({...value,show_timestamps:true})],
    [key('runtime'),value=>({...value,tool_loop_limit:73})],
    [key('mcp'),value=>({...value,local:{command:'unsaved',env:{API:'memory-secret'}}})],
    [key('mcp','project','a'),value=>({...value,project:{...value.project,command:'a-local'}})],
    [key('rules','project','a'),value=>[...value,{match:'a-local',result:'deny'}]],
    [key('rules','project','b'),value=>[...value,{match:'b-local',result:'deny'}]]];
  for(const [identity,edit] of edits)drafts.edit(identity,edit);
  const ticket=drafts.beginSave(key('ui')),ack=snapshot('global-2');ack.config.ui.show_timestamps=true;
  drafts.saved(ticket,{saved:true,revision:'global-2',snapshot:ack,pending:['chat-a']});
  assert.equal(drafts.get(key('ui')).dirty,false);
  assert.equal(drafts.get(key('models')).value.default_model,'p/local');
  assert.equal(drafts.get(key('runtime')).value.tool_loop_limit,73);
  assert.equal(drafts.get(key('mcp')).value.local.env.API,'memory-secret');
  assert.equal(drafts.get(key('models')).revision,'global-2');assert.equal(drafts.get(key('runtime')).conflict,false);
  assert.equal(drafts.get(key('mcp','project','a')).revision,'project-a-1');
  assert.equal(drafts.get(key('rules','project','b')).value.at(-1).match,'b-local');
  assert.deepEqual(drafts.get(key('ui')).lastSave.pending,['chat-a']);
});

test('项目scope保存只推进当前项目，其他项目及全局的草稿保持原样',()=>{
  const drafts=store();
  drafts.edit(key('models'),value=>({...value,default_model:'p/global-draft'}));
  drafts.edit(key('rules','project','a'),value=>[...value,{match:'a-new',result:'deny'}]);
  drafts.edit(key('rules','project','b'),value=>[...value,{match:'b-new',result:'deny'}]);
  const ticket=drafts.beginSave(key('mcp','project','a')),ack=snapshot('project-a-2');
  drafts.saved(ticket,{saved:true,revision:'project-a-2',snapshot:ack});
  assert.equal(drafts.get(key('rules','project','a')).revision,'project-a-2');
  assert.equal(drafts.get(key('rules','project','b')).revision,'project-b-1');
  assert.equal(drafts.get(key('models')).revision,'global-1');
  assert.equal(ticket.payload.project_id,'a');assert.equal(ticket.payload.scope,'project');
  assert.equal(drafts.get(key('rules','project','a')).value.at(-1).match,'a-new');
});

test('外部revision变化即使公开值相同也保留冲突草稿，仅确认重读当前页',()=>{
  const drafts=store();
  drafts.edit(key('models'),value=>({...value,providers:{...value.providers,p:{...value.providers.p,api_key:'unsaved-model-key'}}}));
  drafts.edit(key('ui'),value=>({...value,show_timestamps:true}));
  drafts.receive(snapshot('external-2'));
  const models=drafts.get(key('models'));
  assert.equal(models.value.providers.p.api_key,'unsaved-model-key');assert.equal(models.revision,'global-1');
  assert.equal(models.latestRevision,'external-2');assert.equal(models.conflict,true);
  assert.throws(()=>drafts.beginSave(key('models')),SettingsDraftConflictError);
  assert.throws(()=>drafts.reload(key('models')),/确认/);
  drafts.reload(key('models'),{confirmed:true});
  assert.equal(drafts.get(key('models')).dirty,false);assert.equal(drafts.get(key('models')).revision,'external-2');
  assert.equal(drafts.get(key('ui')).value.show_timestamps,true);assert.equal(drafts.get(key('ui')).dirty,true);
  assert.equal(drafts.get(key('ui')).conflict,true);
});

test('409及校验失败都保留当前值，确认重读一个domain不会重置其它dirty草稿',()=>{
  const drafts=store();drafts.edit(key('runtime'),{tool_loop_limit:99});drafts.edit(key('ui'),{show_timestamps:true});
  const ticket=drafts.beginSave(key('runtime'));
  const error=Object.assign(new Error('fixture conflict'),{status:409});
  drafts.failed(ticket,error);
  assert.equal(drafts.get(key('runtime')).value.tool_loop_limit,99);assert.equal(drafts.get(key('runtime')).conflict,true);
  assert.equal(drafts.get(key('runtime')).saving,false);
  drafts.receive(snapshot('external-2'));drafts.reload(key('runtime'),{confirmed:true});
  assert.equal(drafts.get(key('ui')).dirty,true);assert.equal(drafts.get(key('ui')).value.show_timestamps,true);
});

test('保存期间继续编辑只确认提交快照，保留新编辑并清除已提交密钥',()=>{
  const drafts=store();
  drafts.edit(key('models'),value=>({...value,providers:{...value.providers,p:{...value.providers.p,name:'submitted',api_key:'submitted-secret'}}}));
  const ticket=drafts.beginSave(key('models'));
  drafts.edit(key('models'),value=>({...value,providers:{...value.providers,p:{...value.providers.p,name:'edited-while-saving'}}}));
  const ack=snapshot('global-2');ack.config.providers.p.name='submitted';
  drafts.saved(ticket,{saved:true,revision:'global-2',snapshot:ack});
  const current=drafts.get(key('models'));
  assert.equal(current.value.providers.p.name,'edited-while-saving');assert.equal(current.value.providers.p.api_key,'');
  assert.equal(current.baseline.providers.p.name,'submitted');assert.equal(current.dirty,true);assert.equal(current.saving,false);
  assert.equal(current.value.providers.p.api_key_configured,true);
});

test('保存期间新输入的密钥、null继承与显式清除不会被响应覆盖',()=>{
  const drafts=store();
  drafts.edit(key('models'),value=>({...value,providers:{...value.providers,p:{...value.providers.p,api_key:'submitted-key'}}}));
  const ticket=drafts.beginSave(key('models'));
  drafts.edit(key('models'),value=>({...value,providers:{...value.providers,p:{...value.providers.p,api_key:'newer-key',
    models:{...value.providers.p.models,one:{...value.providers.p.models.one,base_url:null,api_key_clear:true}}}}}));
  drafts.saved(ticket,{saved:true,revision:'global-2',snapshot:snapshot('global-2')});
  const current=drafts.get(key('models')).value.providers.p;
  assert.equal(current.api_key,'newer-key');assert.equal(current.models.one.base_url,null);
  assert.equal(current.models.one.api_key_clear,true);assert.equal(drafts.get(key('models')).dirty,true);
});

test('保存期间退回旧值是新的编辑，不能因编辑次数或当前dirty=false而丢失',()=>{
  const drafts=store();drafts.edit(key('ui'),value=>({...value,show_timestamps:true}));
  const ticket=drafts.beginSave(key('ui'));
  drafts.edit(key('ui'),value=>({...value,show_timestamps:false}));assert.equal(drafts.get(key('ui')).dirty,false);
  const ack=snapshot('global-2');ack.config.ui.show_timestamps=true;
  drafts.saved(ticket,{saved:true,revision:'global-2',snapshot:ack});
  assert.equal(drafts.get(key('ui')).value.show_timestamps,false);
  assert.equal(drafts.get(key('ui')).baseline.show_timestamps,true);assert.equal(drafts.get(key('ui')).dirty,true);
});

test('迟到保存响应不回滚更晚外部来源，失效ticket不能确认另一请求',()=>{
  const drafts=store();drafts.edit(key('runtime'),{tool_loop_limit:51});
  const ticket=drafts.beginSave(key('runtime'));
  drafts.receive(snapshot('external-3'));
  drafts.saved(ticket,{saved:true,revision:'own-save-2',snapshot:snapshot('own-save-2')});
  assert.equal(drafts.getSession().revision,'external-3');
  assert.equal(drafts.get(key('runtime')).value.tool_loop_limit,51);assert.equal(drafts.get(key('runtime')).conflict,true);
  drafts.reload(key('runtime'),{confirmed:true});
  const newer=drafts.beginSave(key('runtime'));
  assert.equal(drafts.saved(ticket,{saved:true,revision:'stale-4',snapshot:snapshot('stale-4')}),false);
  assert.equal(drafts.get(key('runtime')).saving,true);
  drafts.failed(newer,new Error('fixture validation failure'));
  assert.equal(drafts.get(key('runtime')).saving,false);assert.equal(drafts.get(key('runtime')).error,'fixture validation failure');
});

test('提交payload保留未知字段、完整模型目录和显式null，但移除凭据展示标记',()=>{
  const drafts=store();
  drafts.edit(key('models'),value=>({...value,providers:{...value.providers,p:{...value.providers.p,api_key:'memory-key',api_key_clear:false,
    models:{...value.providers.p.models,one:{...value.providers.p.models.one,base_url:null,api_key_clear:true}}}}}));
  const ticket=drafts.beginSave(key('models')),provider=ticket.payload.data.providers.p;
  assert.equal(provider.api_key,'memory-key');assert.equal(provider.api_key_configured,undefined);
  assert.equal(provider.models.one.api_key,null);assert.equal(provider.models.one.api_key_clear,true);
  assert.equal(provider.models.one.extension_configured,'keep-unknown');assert.equal(provider.models.one.base_url,null);
  assert.equal(ticket.payload.project_id,undefined);assert.equal(ticket.payload.data.default_model,'p/one');
  assert.throws(()=>{ticket.payload.data.providers.p.api_key='changed-outside-store';},TypeError);
});

test('关闭再访问同store保留草稿，外观preview与已保存preferences互不冒充',()=>{
  const drafts=store();drafts.edit(key('web'),value=>({...value,theme:'dark'}));
  drafts.receive(snapshot('global-2'));
  assert.equal(drafts.get(key('web')).value.theme,'dark');assert.equal(drafts.get(key('web')).conflict,false);
  assert.equal(drafts.getSession().snapshot.preferences.theme,'light');
  const ticket=drafts.beginSave(key('web'));
  assert.equal(ticket.payload.revision,undefined);assert.equal(ticket.payload.project_id,undefined);
  drafts.saved(ticket,{saved:true,preferences:{theme:'dark',reduce_motion:false,reduce_transparency:false}});
  assert.equal(drafts.get(key('web')).dirty,false);assert.equal(drafts.getSession().snapshot.preferences.theme,'dark');
  drafts.edit(key('web'),value=>({...value,reduce_motion:true}));
  assert.equal(drafts.get(key('web')).value.reduce_motion,true);
  assert.equal(drafts.getSession().snapshot.preferences.reduce_motion,false);
});

test('来源快照和保存ticket都隔离引用，来源密钥不会进入baseline或storage',()=>{
  const storageCalls=[];
  const before=Object.getOwnPropertyDescriptor(globalThis,'localStorage');
  Object.defineProperty(globalThis,'localStorage',{configurable:true,get(){storageCalls.push('read');throw new Error('storage forbidden');}});
  try{
    const data=snapshot();data.config.providers.p.api_key='server-secret';data.config.providers.p.models.one.api_key='server-model-secret';
    data.global_mcp.global.env.TOKEN='server-env-secret';data.global_mcp.global.headers={Authorization:'server-header-secret'};
    const drafts=new SettingsDraftStore();drafts.receive(data);
    data.config.ui.show_timestamps=true;
    assert.equal(drafts.get(key('ui')).value.show_timestamps,false);
    assert.equal(drafts.get(key('models')).baseline.providers.p.api_key,'');
    assert.equal(drafts.get(key('models')).baseline.providers.p.models.one.api_key,'');
    assert.equal(drafts.get(key('mcp')).baseline.global.env.TOKEN,'');
    assert.equal(drafts.get(key('mcp')).baseline.global.headers.Authorization,'');
    drafts.edit(key('mcp'),value=>({...value,global:{...value.global,env:{TOKEN:'memory-env-secret'},env_clear:['OLD'],env_remove:['REMOVED']}}));
    const ticket=drafts.beginSave(key('mcp'));
    assert.equal(ticket.payload.data.global.env.TOKEN,'memory-env-secret');
    assert.deepEqual(ticket.payload.data.global.env_clear,['OLD']);assert.deepEqual(ticket.payload.data.global.env_remove,['REMOVED']);
    assert.equal(ticket.payload.data.global.env_configured,undefined);assert.deepEqual(storageCalls,[]);
  }finally{
    if(before)Object.defineProperty(globalThis,'localStorage',before);else delete globalThis.localStorage;
  }
});

test('全局保存后项目dirty直到项目新版本确认仍保留，不伪造组合revision',()=>{
  const drafts=store();drafts.edit(key('rules','project','a'),value=>[...value,{match:'unsaved-project',result:'deny'}]);
  const ticket=drafts.beginSave(key('models'));
  drafts.saved(ticket,{saved:true,revision:'global-2',snapshot:snapshot('global-2')});
  assert.equal(drafts.get(key('rules','project','a')).revision,'project-a-1');
  drafts.receive(snapshot('project-a-after-global'),'a');
  const project=drafts.get(key('rules','project','a'));
  assert.equal(project.value.at(-1).match,'unsaved-project');assert.equal(project.revision,'project-a-1');
  assert.equal(project.latestRevision,'project-a-after-global');assert.equal(project.conflict,true);
});

test('尚未加载不会造空保存，保存中不能重读当前页，订阅不因get重复触发',()=>{
  const drafts=new SettingsDraftStore();assert.equal(drafts.get(key('models')),undefined);
  assert.throws(()=>drafts.beginSave(key('models')),/读取/);
  let calls=0;const off=drafts.subscribe(()=>calls++);drafts.receive(snapshot());const version=drafts.getSnapshot();
  drafts.get(key('ui'));drafts.get(key('ui'));assert.equal(drafts.getSnapshot(),version);assert.equal(calls,1);
  drafts.edit(key('ui'),{show_timestamps:true});const ticket=drafts.beginSave(key('ui'));
  assert.throws(()=>drafts.reload(key('ui'),{confirmed:true}),/保存/);
  drafts.failed(ticket,new Error('validation'));assert.equal(calls,4);off();
  drafts.edit(key('ui'),{show_timestamps:false});assert.equal(calls,4);
});



test('未完成高级JSON文本跨页面和关闭设置保留，只阻止本域保存',()=>{
  const drafts=store(),execution=key('execution');
  drafts.setEditor(execution,'command_profiles',{text:'[{"name":',valid:false,source:'[]'});
  drafts.get(key('models'));drafts.get(key('ui'));
  assert.equal(drafts.getEditor(execution,'command_profiles').text,'[{"name":');
  assert.deepEqual(drafts.get(execution).invalidEditors,['command_profiles']);assert.equal(drafts.get(execution).dirty,true);
  assert.throws(()=>drafts.beginSave(execution),/JSON/);
  drafts.edit(key('ui'),value=>({...value,show_timestamps:true}));const ticket=drafts.beginSave(key('ui'));
  const ack=snapshot('global-2');ack.config.ui.show_timestamps=true;
  drafts.saved(ticket,{saved:true,revision:'global-2',snapshot:ack});
  assert.equal(drafts.getEditor(execution,'command_profiles').text,'[{"name":');
  assert.equal(drafts.get(execution).revision,'global-2');assert.equal(drafts.get(execution).conflict,false);
  assert.throws(()=>drafts.reload(execution),/确认/);
});

test('确认重读只清当前cell的raw编辑器，其他域未完成文本仍在',()=>{
  const drafts=store();
  drafts.setEditor(key('execution'),'command_profiles',{text:'[',valid:false,source:'[]'});
  drafts.setEditor(key('mcp','project','a'),'advanced',{text:'{"unfinished":',valid:false,source:'{}'});
  drafts.reload(key('execution'),{confirmed:true});
  assert.equal(drafts.getEditor(key('execution'),'command_profiles'),undefined);
  assert.deepEqual(drafts.get(key('execution')).invalidEditors,[]);
  assert.equal(drafts.getEditor(key('mcp','project','a'),'advanced').text,'{"unfinished":');
});

test('保存只清提交版本的raw编辑器，保存期间新JSON输入保留且禁下次保存',()=>{
  const drafts=store(),execution=key('execution');
  drafts.setEditor(execution,'command_profiles',{text:'[]',valid:true,source:'[]'});
  const first=drafts.beginSave(execution);
  drafts.saved(first,{saved:true,revision:'global-2',snapshot:snapshot('global-2')});
  assert.equal(drafts.getEditor(execution,'command_profiles'),undefined);
  drafts.setEditor(execution,'command_profiles',{text:'[]',valid:true,source:'[]'});
  const second=drafts.beginSave(execution);
  drafts.setEditor(execution,'command_profiles',{text:'[{"new":',valid:false,source:'[]'});
  drafts.saved(second,{saved:true,revision:'global-3',snapshot:snapshot('global-3')});
  assert.equal(drafts.getEditor(execution,'command_profiles').text,'[{"new":');
  assert.equal(drafts.get(execution).dirty,true);assert.equal(drafts.get(execution).saving,false);
  assert.throws(()=>drafts.beginSave(execution),/JSON/);
});

test('raw文本修正后不会写入payload，未完成文本的外部冲突不会静默清除',()=>{
  const drafts=store(),execution=key('execution');
  drafts.setEditor(execution,'command_profiles',{text:'[',valid:false,source:'[]'});
  drafts.receive(snapshot('external-2'));
  assert.equal(drafts.get(execution).conflict,true);assert.equal(drafts.getEditor(execution,'command_profiles').text,'[');
  drafts.reload(execution,{confirmed:true});
  drafts.setEditor(execution,'command_profiles',{text:'[ ]',valid:true,source:'[]'});
  const ticket=drafts.beginSave(execution);
  assert.equal(ticket.payload.data.editors,undefined);assert.equal(ticket.payload.data.invalidEditors,undefined);
  assert.equal(JSON.stringify(ticket.payload).includes('[ ]'),false);
  assert.equal(ticket.editors.command_profiles.text,'[ ]');
});

const validationError=issues=>Object.assign(new Error('请修正标出的设置。'),{status:400,data:{issues}});
test('字段校验问题跨分类保留，编辑只清除实际修改字段的错误',()=>{
  const drafts=store(),models=key('models');
  drafts.setIssues(models,[{domain:'models',path:['providers','p','name'],message:'名称错误'},
    {domain:'models',path:['providers','p','base_url'],message:'URL错误'}]);
  drafts.get(key('ui'));
  drafts.edit(models,value=>({...value,providers:{...value.providers,p:{...value.providers.p,api_mode:'responses'}}}));
  assert.equal(drafts.get(models).issues.length,2);
  drafts.edit(models,value=>({...value,providers:{...value.providers,p:{...value.providers.p,name:'repaired'}}}));
  assert.deepEqual(drafts.get(models).issues.map(issue=>issue.path.at(-1)),['base_url']);
  drafts.edit(models,value=>({...value,providers:{...value.providers,p:{...value.providers.p,base_url:'https://repaired.invalid/v1'}}}));
  assert.deepEqual(drafts.get(models).issues,[]);assert.equal(drafts.get(models).error,'');
});

test('迟到失败只标出提交后仍未修改的字段，已修正字段不再标红',()=>{
  const drafts=store(),models=key('models');
  drafts.edit(models,value=>({...value,providers:{...value.providers,p:{...value.providers.p,name:'submitted'}}}));
  const ticket=drafts.beginSave(models);
  drafts.edit(models,value=>({...value,providers:{...value.providers,p:{...value.providers.p,name:'repaired-after-submit'}}}));
  drafts.failed(ticket,validationError([{domain:'models',path:['providers','p','name'],message:'旧名称错误'},
    {domain:'models',path:['providers','p','base_url'],message:'URL仍错误'}]));
  assert.deepEqual(drafts.get(models).issues.map(issue=>issue.message),['URL仍错误']);
  assert.equal(drafts.get(models).value.providers.p.name,'repaired-after-submit');
  assert.equal(drafts.get(models).saving,false);
  const second=drafts.beginSave(models);
  drafts.edit(models,value=>({...value,providers:{...value.providers,p:{...value.providers.p,base_url:'https://fresh.invalid/v1'}}}));
  drafts.failed(second,validationError([{domain:'models',path:['providers','p','base_url'],message:'旧URL错误'}]));
  assert.deepEqual(drafts.get(models).issues,[]);assert.equal(drafts.get(models).error,'');
});

test('迟到非结构化错误不污染新编辑，409仍保留整页冲突',()=>{
  const drafts=store(),runtime=key('runtime');
  const first=drafts.beginSave(runtime);drafts.edit(runtime,{tool_loop_limit:60});drafts.failed(first,new Error('old failure'));
  assert.equal(drafts.get(runtime).error,'');
  const second=drafts.beginSave(runtime);drafts.edit(runtime,{tool_loop_limit:61});drafts.failed(second,Object.assign(new Error('conflict'),{status:409}));
  assert.equal(drafts.get(runtime).conflict,true);assert.match(drafts.get(runtime).error,/配置已更新/);
});

test('坏领域读取保留已有草稿并禁存，首次读取缺数据不伪造空领域',()=>{
  const drafts=store(),mcp=key('mcp');
  drafts.edit(mcp,value=>({...value,new:{type:'stdio',command:'local-command'}}));
  const before=drafts.get(mcp).value,broken=snapshot('global-broken');delete broken.global_mcp;
  broken.domain_errors={global_mcp:[{domain:'mcp',path:[],message:'MCP文件无法解析'}]};
  drafts.receive(broken);
  assert.deepEqual(drafts.get(mcp).value,before);assert.equal(drafts.get(mcp).blocked,true);assert.equal(drafts.get(mcp).dirty,true);
  assert.throws(()=>drafts.beginSave(mcp),/无法解析/);assert.throws(()=>drafts.reload(mcp,{confirmed:true}),/无法解析/);
  assert.equal(drafts.get(key('models')).blocked,false);
  const empty=new SettingsDraftStore();empty.receive(broken);
  assert.equal(empty.get(mcp).value,undefined);assert.equal(empty.get(mcp).baseline,undefined);assert.equal(empty.get(mcp).blocked,true);
  assert.throws(()=>empty.beginSave(mcp),/无法解析/);
  empty.receive(snapshot('global-repaired'));assert.equal(empty.get(mcp).blocked,false);assert.equal(empty.get(mcp).value.global.command,'global-command');
});

test('项目来源中的全局错误不会封锁全局草稿，保存其他分类不覆盖坏领域旧值',()=>{
  const drafts=store(),globalMcp=key('mcp'),projectMcp=key('mcp','project','a');
  const projectBroken=snapshot('project-a-broken');delete projectBroken.global_mcp;
  projectBroken.domain_errors={global_mcp:[{domain:'mcp',path:[],message:'global failure'}]};
  drafts.receive(projectBroken,'a');assert.equal(drafts.get(globalMcp).blocked,false);assert.equal(drafts.get(projectMcp).blocked,false);
  drafts.edit(globalMcp,value=>({...value,new:{command:'keep-this-draft'}}));
  const ticket=drafts.beginSave(key('ui')),ack=snapshot('global-2');delete ack.global_mcp;
  ack.domain_errors={global_mcp:[{domain:'mcp',path:[],message:'read failed'}]};
  drafts.saved(ticket,{saved:true,revision:'global-2',snapshot:ack});
  assert.equal(drafts.get(globalMcp).value.new.command,'keep-this-draft');assert.equal(drafts.get(globalMcp).blocked,true);
  assert.equal(drafts.get(key('ui')).blocked,false);assert.equal(drafts.get(key('ui')).saving,false);
});

test('保存已确认而读回失败仍保留所提交值，不以缺失字段重置草稿',()=>{
  const drafts=store(),runtime=key('runtime');drafts.edit(runtime,{tool_loop_limit:72});
  const ticket=drafts.beginSave(runtime),ack=snapshot('global-2');delete ack.config.runtime;
  ack.domain_errors={runtime:[{domain:'runtime',path:[],message:'read failed'}]};
  drafts.saved(ticket,{saved:true,revision:'global-2',snapshot:ack});
  assert.equal(drafts.get(runtime).value.tool_loop_limit,72);assert.equal(drafts.get(runtime).blocked,true);assert.equal(drafts.get(runtime).saving,false);
});

test('可读MCP字段错误呈现原值并允许修复，编辑只清实际修改的问题',()=>{
  const broken=snapshot();broken.global_mcp.global.type='stdio';broken.global_mcp.global.tool_timeout_seconds=0;
  broken.global_mcp.global.command='';
  broken.domain_errors={global_mcp:[{domain:'mcp',path:['global','tool_timeout_seconds'],message:'超时必须大于0'},
    {domain:'mcp',path:['global','command'],message:'请填写命令'}]};
  const drafts=new SettingsDraftStore();drafts.receive(broken);const mcp=key('mcp');
  assert.equal(drafts.get(mcp).blocked,false);assert.equal(drafts.get(mcp).value.global.tool_timeout_seconds,0);
  assert.equal(drafts.get(mcp).issues.length,2);
  drafts.edit(mcp,value=>({...value,global:{...value.global,tool_timeout_seconds:60}}));
  assert.deepEqual(drafts.get(mcp).issues.map(issue=>issue.path.at(-1)),['command']);
  drafts.edit(mcp,value=>({...value,global:{...value.global,command:'python'}}));
  assert.deepEqual(drafts.get(mcp).issues,[]);assert.equal(drafts.get(mcp).blocked,false);
  assert.equal(drafts.beginSave(mcp).payload.data.global.tool_timeout_seconds,60);
});

test('已有清洁草稿读取可读MCP错误会接收新原值和问题，不误判为不可读',()=>{
  const drafts=store(),mcp=key('mcp');drafts.get(mcp);
  const broken=snapshot('global-2');broken.global_mcp.global.tool_timeout_seconds={invalid:1};
  broken.domain_errors={global_mcp:[{domain:'mcp',path:['global','tool_timeout_seconds'],message:'超时必须是数值'}]};
  drafts.receive(broken);
  assert.equal(drafts.get(mcp).blocked,false);assert.deepEqual(drafts.get(mcp).value.global.tool_timeout_seconds,{invalid:1});
  assert.equal(drafts.get(mcp).issues[0].message,'超时必须是数值');
  drafts.edit(mcp,value=>({...value,global:{...value.global,tool_timeout_seconds:30}}));
  drafts.receive(broken);
  assert.equal(drafts.get(mcp).value.global.tool_timeout_seconds,30);assert.deepEqual(drafts.get(mcp).issues,[]);
});

test('不可读MCP恢复为可读时移除旧文件错误，保留草稿与版本冲突',()=>{
  const drafts=store(),mcp=key('mcp');drafts.edit(mcp,value=>({...value,new:{command:'local'}}));
  const unreadable=snapshot('global-2');delete unreadable.global_mcp;
  unreadable.domain_errors={global_mcp:[{domain:'mcp',path:[],message:'文件无法读取'}]};drafts.receive(unreadable);
  assert.equal(drafts.get(mcp).blocked,true);
  drafts.receive(snapshot('global-3'));
  assert.equal(drafts.get(mcp).blocked,false);assert.equal(drafts.get(mcp).value.new.command,'local');
  assert.equal(drafts.get(mcp).conflict,true);assert.deepEqual(drafts.get(mcp).issues,[]);
});
