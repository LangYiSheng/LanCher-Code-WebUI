import {useEffect,useRef,useState} from 'react';
import type {ChatSummary,Dict,Preferences,Project} from './types';
import {api,patch} from './api';
import {Select} from './Select';
import {Icon,Spinner} from './Icon';
import {useDialogs} from './Dialogs';
import {Field,Numeric,Advanced,JsonEditor} from './SettingsFields';
import {SettingsModels} from './SettingsModels';
import {SettingsStorage} from './SettingsStorage';
import {SettingsAbout} from './SettingsAbout';
import {useSettingsDrafts,type SettingsDraftStore,type SettingsDraftKey} from './settingsDrafts';
import './Settings.css';
function SecretMap({label,value,onChange,removed}:{label:string;value:Dict;onChange:(value:Dict,removed:string[])=>void;removed:string[]}){
  const {prompt}=useDialogs();
  return <div className="secret-map"><div className="section-heading"><h3>{label}</h3><button className="text-button" onClick={()=>void prompt({title:'新增'+label+'字段',label:'字段名称',confirmLabel:'添加',maxLength:200,validate:key=>Object.hasOwn(value,key)?'这个字段已存在。':/\s/.test(key)?'字段名称不能包含空白。':undefined,onSubmit:key=>onChange({...value,[key]:''},removed.filter(item=>item!==key))})}>新增字段</button></div>{Object.entries(value||{}).map(([key,item])=><div className="map-row" key={key}><code>{key}</code><input aria-label={label+' '+key} type="password" autoComplete="new-password" value={item??''} placeholder="留空保留已配置值" onChange={e=>onChange({...value,[key]:e.target.value},removed.filter(item=>item!==key))}/><button className="icon-button" title="删除这个字段" aria-label={'删除'+label+' '+key} onClick={()=>{const next={...value};delete next[key];onChange(next,[...new Set([...removed,key])]);}}><Icon name="trash" size={14}/></button></div>)}<p className="small-note">已配置的值不会显示。留空保留原值；删除会移除整个字段。</p></div>;
}
function McpEditor({value,onChange}:{value:Dict;onChange:(value:Dict)=>void}){
  const {prompt,confirm}=useDialogs();
  const [selected,setSelected]=useState(Object.keys(value||{})[0]||'');const server=value?.[selected];const update=(next:Dict)=>onChange({...value,[selected]:next});
  useEffect(()=>{if(!value?.[selected])setSelected(Object.keys(value||{})[0]||'');},[value,selected]);
  return <><div className="editor-heading"><h3>MCP 服务</h3><button className="secondary-button" onClick={()=>void prompt({title:'新增 MCP 服务',label:'服务名称',confirmLabel:'添加',maxLength:100,validate:name=>Object.hasOwn(value,name)?'这个 MCP 服务名称已存在。':undefined,onSubmit:name=>{onChange({...value,[name]:{type:'stdio',enabled:true,command:'',args:[],env:{},headers:{},tool_timeout_seconds:60}});setSelected(name);}})}><Icon name="plus" size={14}/>新增服务</button></div><div className="model-selector"><Select aria-label="选择 MCP 服务" value={selected} onChange={e=>setSelected(e.target.value)}><option value="">选择服务…</option>{Object.keys(value||{}).map(name=><option key={name}>{name}</option>)}</Select>{server&&<button className="danger-text" onClick={async()=>{if(!await confirm({title:'删除 MCP 服务',message:'将从待保存配置中移除 '+selected+'。保存设置后生效。',confirmLabel:'移除服务',danger:true}))return;const next={...value};delete next[selected];onChange(next);}}>删除服务</button>}</div>{server&&<><div className="connection-settings"><Field label="传输类型"><Select value={server.type||'stdio'} onChange={e=>update({...server,type:e.target.value})}><option value="stdio">标准输入输出（stdio）</option><option value="http">HTTP</option></Select></Field><Field label="启用"><input type="checkbox" checked={server.enabled!==false} onChange={e=>update({...server,enabled:e.target.checked})}/></Field>{server.type==='http'?<Field label="服务 URL"><input value={server.url||''} onChange={e=>update({...server,url:e.target.value})}/></Field>:<><Field label="启动命令"><input value={server.command||''} onChange={e=>update({...server,command:e.target.value})}/></Field><Field label="命令参数" note="每行一个参数"><textarea value={(server.args||[]).join('\n')} onChange={e=>update({...server,args:e.target.value.split('\n').filter(Boolean)})}/></Field></>}</div><Advanced title="MCP 高级设置" note={server.type==='http'?'请求头与超时':'环境变量与超时'}><div className="field-grid numeric-settings"><Field label="启动超时（秒）" note="留空使用默认值"><Numeric min={1} value={server.startup_timeout_seconds} onChange={x=>update({...server,startup_timeout_seconds:x})}/></Field><Field label="工具超时（秒）" note="留空使用默认值"><Numeric min={1} value={server.tool_timeout_seconds} onChange={x=>update({...server,tool_timeout_seconds:x})}/></Field><Field label="关闭超时（秒）" note="留空使用默认值"><Numeric min={1} value={server.close_timeout_seconds} onChange={x=>update({...server,close_timeout_seconds:x})}/></Field></div>{server.type==='http'?<SecretMap label="请求头" value={server.headers||{}} onChange={(headers,headers_remove)=>update({...server,headers,headers_remove,headers_clear:(server.headers_clear||[]).filter((name:string)=>!headers[name])})} removed={server.headers_remove||[]}/>:<SecretMap label="环境变量" value={server.env||{}} onChange={(env,env_remove)=>update({...server,env,env_remove,env_clear:(server.env_clear||[]).filter((name:string)=>!env[name])})} removed={server.env_remove||[]}/> }</Advanced></>}</>;
}
function RulesEditor({value,onChange}:{value:Dict[];onChange:(value:Dict[])=>void}){return <><div className="editor-heading"><h3>持久拒绝规则</h3><button className="secondary-button" onClick={()=>onChange([...value,{match:'',result:'deny',match_kind:'exact'}])}><Icon name="plus" size={14}/>新增规则</button></div><p className="small-note">这些规则会持续拒绝匹配操作。普通操作授权通过聊天中的审批处理。</p>{value.map((rule,index)=>{const set=(key:string,item:any)=>onChange(value.map((x,i)=>i===index?{...x,[key]:item}:x));return <div className="rule-card" key={index}><div className="connection-settings"><Field label="匹配目标"><input value={rule.match||''} onChange={e=>set('match',e.target.value)}/></Field><Field label="匹配方式"><Select value={rule.match_kind||'exact'} onChange={e=>set('match_kind',e.target.value)}><option value="exact">精确匹配</option><option value="glob">Glob 模式</option></Select></Field><Field label="命令目录" note="可选"><input value={rule.command_cwd||''} onChange={e=>set('command_cwd',e.target.value||null)}/></Field><Field label="命令 Shell" note="可选"><input value={rule.command_shell||''} onChange={e=>set('command_shell',e.target.value||null)}/></Field></div><button className="danger-text" onClick={()=>onChange(value.filter((_,i)=>i!==index))}>移除规则</button></div>;})}{!value.length&&<div className="panel-empty">这一层没有持久拒绝规则。</div>}</>;}

const GROUPS=[
  {label:'个人偏好',items:[['appearance','外观','sun'],['ui','输入与显示','chat']]},
  {label:'模型与能力',items:[['models','模型与供应商','globe'],['mcp','MCP 服务','mcp'],['rules','权限规则','shield']]},
  {label:'运行与数据',items:[['runtime','Agent 行为','spark'],['execution','执行与进程','terminal'],['storage','数据与历史','history'],['about','关于','info']]},
];
const DESCRIPTIONS:Record<string,string>={appearance:'设置 WebUI 外观。选择会实时预览，保存后保留。',ui:'调整显示与输入习惯，与 TUI 共用这些设置。',models:'管理连接和模型目录。新聊天采用默认模型，当前对话的模型选择保持不变。',mcp:'按配置层管理服务。项目中的同名服务覆盖全局配置。',rules:'持久规则会拒绝匹配的操作，对话中的审批仍在聊天内处理。',runtime:'设置工作阶段、访问范围与 Agent 的运行行为。',execution:'控制并发、进程和输出资源。保存后需重启服务应用。',storage:'查阅归档对话，管理浏览器输入草稿。',about:'查看前端发布版本与固定 SDK 来源。'};
const RUNTIME_LABELS:Dict={tool_loop_limit:'工具循环上限',unknown_tool_streak_limit:'连续未知工具上限',output_continuation_limit:'输出续写上限'};
const LIMIT_LABELS:Dict={max_concurrency:'最大并发调用',max_processes:'最大进程总数',max_processes_per_session:'每会话进程上限',output_limit_bytes:'输出存储限制（bytes）',max_read_chars:'单次读取字符上限',stop_grace_seconds:'停止宽限（秒）',drain_timeout_seconds:'输出收尾超时（秒）'};
type Props={drafts:SettingsDraftStore;project?:Project;preferences:Preferences;onPreview:(value:Preferences)=>void;onClose:()=>void;onSaved:()=>Promise<void>;notify:(text:string)=>void;initialSection?:string;chats:ChatSummary[];projects:Project[];onOpenArchived:(id:string)=>void;onRestoreArchived:(id:string)=>Promise<void>};
export function Settings({drafts:memory,project,preferences,onPreview,onClose,onSaved,notify,initialSection,chats,projects,onOpenArchived,onRestoreArchived}:Props){
  const store=useSettingsDrafts(memory),dialogs=useDialogs();
  const [section,setSection]=useState(initialSection&&DESCRIPTIONS[initialSection]?initialSection:'appearance');
  const [mcpScope,setMcpScope]=useState<'global'|'project'>('global'),[rulesScope,setRulesScope]=useState<'global'|'project'>('global');
  const [loading,setLoading]=useState(true),[loadErrors,setLoadErrors]=useState<Record<string,string>>({});
  const mounted=useRef(true),activeProject=useRef(project?.id);activeProject.current=project?.id;
  const loadGeneration=useRef(0),loadController=useRef<AbortController|null>(null);
  function keyFor(name:string,layer?:'global'|'project'):SettingsDraftKey{
    const domain=name==='appearance'?'web':name as SettingsDraftKey['domain'];
    const effectiveLayer=layer==='project'&&project?'project':'global';
    const scope=name==='rules'?(effectiveLayer==='project'?'project':'user'):effectiveLayer;
    return {domain,scope,...(scope==='project'&&project?{projectId:project.id}:{})} as SettingsDraftKey;
  }
  const effectiveMcpScope=mcpScope==='project'&&project?'project':'global',effectiveRulesScope=rulesScope==='project'&&project?'project':'global';
  const activeScope=section==='mcp'?effectiveMcpScope:section==='rules'?effectiveRulesScope:'global';
  const loadError=loadErrors[activeScope==='project'?'project':'global']||'';
  const readOnly=section==='storage'||section==='about';
  const key=keyFor(readOnly?'appearance':section,activeScope),entry=store.get(key);
  const models=store.get(keyFor('models'))?.value||{};
  const ui=store.get(keyFor('ui'))?.value||{},runtime=store.get(keyFor('runtime'))?.value||{},execution=store.get(keyFor('execution'))?.value||{};
  const prefs=(store.get(keyFor('appearance'))?.value||preferences) as Preferences;
  const mcp=store.get(keyFor('mcp',effectiveMcpScope))?.value||{},rules=store.get(keyFor('rules',effectiveRulesScope))?.value||[];
  const dirty=!!entry?.dirty,conflict=!!entry?.conflict,saving=!!entry?.saving;
  const title=GROUPS.flatMap(group=>group.items).find(([name])=>name===section)?.[1]||'设置';
  const scopeLabel=section==='storage'?'所有已登记项目':section==='appearance'?'WebUI 外观偏好':activeScope==='project'?'项目 · '+(project?.name||'未选择项目'):'用户全局配置';
  async function load(showLoading=true){
    if(!mounted.current||activeProject.current!==project?.id)return null;
    loadController.current?.abort();const controller=new AbortController();loadController.current=controller;const token=++loadGeneration.current;
    if(showLoading)setLoading(true);setLoadErrors({});
    const requests=[{projectId:undefined as string|undefined,path:'/api/settings'},...(project?[{projectId:project.id,path:'/api/settings?project_id='+encodeURIComponent(project.id)}]:[])];
    try{
      const results=await Promise.allSettled(requests.map(async request=>({projectId:request.projectId,data:await api(request.path,{signal:controller.signal})})));
      if(controller.signal.aborted||token!==loadGeneration.current||!mounted.current||activeProject.current!==project?.id)return null;
      const failures:Record<string,string>={},loaded={global:false,project:false};
      for(let index=0;index<results.length;index++){const result=results[index],source=requests[index].projectId?'project':'global';if(result.status==='fulfilled'){store.receive({...result.value.data,preferences:result.value.data.preferences||preferences},result.value.projectId);loaded[source]=true;}else failures[source]=result.reason instanceof Error?result.reason.message:String(result.reason);}
      setLoadErrors(failures);return loaded;
    }finally{if(!controller.signal.aborted&&token===loadGeneration.current&&mounted.current&&activeProject.current===project?.id)setLoading(false);}
  }
  useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;};},[]);
  useEffect(()=>{void load();return()=>{loadGeneration.current++;loadController.current?.abort();};},[project?.id]);
  useEffect(()=>{if(initialSection&&DESCRIPTIONS[initialSection])setSection(initialSection);},[initialSection]);
  useEffect(()=>{if(!project){setMcpScope('global');setRulesScope('global');}},[project?.id]);
  useEffect(()=>{if(section==='appearance'||store.get(keyFor('appearance'))?.dirty)onPreview(prefs);},[section,prefs,preferences]);
  function edit(name:string,value:Dict){store.edit(keyFor(name),value);}
  function hasDirty(name:string){if(name==='storage'||name==='about')return false;if(['mcp','rules'].includes(name))return !!store.get(keyFor(name,'global'))?.dirty||!!project&&!!store.get(keyFor(name,'project'))?.dirty;return !!store.get(keyFor(name))?.dirty;}
  async function save(){
    if(readOnly||!dirty||saving||conflict)return;
    const sourceContext=project?.id;let ticket:ReturnType<SettingsDraftStore['beginSave']>;
    try{ticket=store.beginSave(key);}catch(reason){setLoadErrors(values=>({...values,[activeScope==='project'?'project':'global']:reason instanceof Error?reason.message:String(reason)}));return;}
    try{const response=await patch('/api/settings',ticket.payload);store.saved(ticket,response);notify('设置已保存。');}
    catch(reason){store.failed(ticket,reason);return;}
    try{await onSaved();}catch{notify('设置已保存，工作台状态刷新失败，可稍后重新读取。');}
    if(mounted.current&&activeProject.current===sourceContext)await load(false);
  }
  async function reloadCurrent(){
    if(saving)return;
    if((dirty||conflict)&&!await dialogs.confirm({title:'重新读取当前设置',message:'放弃“'+title+' · '+scopeLabel+'”的未保存修改，读取最新配置。其他页面的草稿会保留。',confirmLabel:'重新读取'}))return;
    const sourceContext=project?.id,version=store.get(key)?.editVersion;
    if(!mounted.current||activeProject.current!==sourceContext)return;
    const loaded=await load(false);
    if(!mounted.current||activeProject.current!==sourceContext)return;
    if(!loaded?.[key.scope==='project'?'project':'global'])return;
    if(version!==undefined&&store.get(key)?.editVersion!==version){notify('读取期间有新的修改，当前草稿已保留。');return;}
    store.reload(key,{confirmed:true});
  }
  const lastSave=entry?.lastSave as Dict|undefined;
  const pending=Array.isArray(lastSave?.pending)?lastSave.pending.length>0:!!lastSave?.pending;
  const applied=Array.isArray(lastSave?.applied)?lastSave.applied.length>0:!!lastSave?.applied;
  const savedState=lastSave?.restart_required?'已保存 · 重启服务后应用':pending?'已保存 · 运行中的聊天将在安全边界应用':lastSave?applied?'已保存 · 空闲对话已应用':'设置已保存':'当前页面没有未保存修改';
  return <section className="settings-page settings-redesign">
    <div className="settings-body">
      <nav className="settings-nav" aria-label="设置分类"><div className="settings-nav-title">设置</div>{GROUPS.map(group=><div className="settings-nav-group" key={group.label}><h2>{group.label}</h2>{group.items.map(([name,label,icon])=><button key={name} className={'settings-nav-item '+(section===name?'active':'')} aria-current={section===name?'page':undefined} onClick={()=>setSection(name)}><Icon name={icon} size={16}/><span>{label}</span>{hasDirty(name)&&<span className="settings-draft-dot" role="img" aria-label="有未保存修改" title="有未保存修改"/>}</button>)}</div>)}</nav>
      <div className="settings-workspace">
        <header className="settings-section-header"><div><h1>{title}</h1><p>{DESCRIPTIONS[section]}</p></div><div className="settings-section-actions">{!readOnly&&<span className={'settings-save-badge '+(conflict?'conflict':dirty?'dirty':saving?'saving':'')} role="status">{saving?'保存中':conflict?'配置已变化':dirty?'未保存':'已保存'}</span>}<button className="icon-button" aria-label="返回工作台" title="返回工作台" onClick={onClose}><Icon name="close" size={18}/></button></div></header>
        {section!=='about'&&<div className="settings-scope-bar"><span><Icon name={activeScope==='project'?'folder':section==='appearance'?'monitor':'globe'} size={13}/>{scopeLabel}</span>{['mcp','rules'].includes(section)&&<Select aria-label="配置作用范围" value={activeScope} onChange={event=>section==='mcp'?setMcpScope(event.target.value as 'global'|'project'):setRulesScope(event.target.value as 'global'|'project')}><option value="global">{section==='rules'?'用户规则':'用户全局'}</option><option value="project" disabled={!project}>项目 · {project?.name||'未选择项目'}</option></Select>}</div>}
        <div className="settings-content" key={section+(section==='mcp'||section==='rules'?':'+activeScope:'')}>
          {section!=='about'&&(loadError||entry?.error)&&<div className="settings-error inline-error" role="alert"><span>{loadError||String(entry?.error)}</span><button className="text-button" disabled={saving} onClick={()=>void reloadCurrent()}>重新读取当前页</button></div>}
          {section!=='about'&&conflict&&!entry?.error&&<div className="settings-error inline-error" role="alert"><span>配置在其他界面发生变化。当前草稿已保留，请重新读取当前页后再保存。</span><button className="text-button" onClick={()=>void reloadCurrent()}>重新读取当前页</button></div>}
          {section==='about'?<SettingsAbout/>:loading?<div className="panel-empty"><Spinner/>正在读取配置…</div>:!entry&&section!=='storage'?<div className="panel-empty">尚未读取到这页设置。请重新读取当前页后编辑。<button className="text-button" onClick={()=>void reloadCurrent()}>重新读取</button></div>:<>
            {section==='appearance'&&<><div className="settings-subheading"><div><h3>主题</h3><p>选择浅色、深色或跟随系统。</p></div></div><div className="theme-options">{[['light','浅色','sun'],['dark','深色','moon'],['system','跟随系统','monitor']].map(([name,label,icon])=><button className={prefs.theme===name?'selected':''} key={name} onClick={()=>store.edit(keyFor('appearance'),{...prefs,theme:name})}><span className={'theme-preview '+name}><i/><i/><i/></span><span><Icon name={icon} size={16}/>{label}{prefs.theme===name&&<Icon name="check" size={15}/>}</span></button>)}</div><Field label="减少透明效果" note="减少半透明遮罩与背景效果"><input type="checkbox" checked={!!prefs.reduce_transparency} onChange={event=>store.edit(keyFor('appearance'),{...prefs,reduce_transparency:event.target.checked})}/></Field><Field label="减少动画" note="关闭过渡与动画，也遵循操作系统偏好"><input type="checkbox" checked={prefs.reduce_motion} onChange={event=>store.edit(keyFor('appearance'),{...prefs,reduce_motion:event.target.checked})}/></Field></>}
            {section==='ui'&&<><Field label="显示时间戳" note="在聊天消息旁显示发送时间"><input type="checkbox" checked={!!ui.show_timestamps} onChange={event=>edit('ui',{...ui,show_timestamps:event.target.checked})}/></Field><Field label="显示思考状态" note="只改变轨迹显示，推理强度由对话选择"><input type="checkbox" checked={ui.show_thinking_status!==false} onChange={event=>edit('ui',{...ui,show_thinking_status:event.target.checked})}/></Field><Field label="忙时默认输入操作" note="当前任务运行时，Enter 如何处理输入"><Select value={ui.busy_enter_action||'follow_up'} onChange={event=>edit('ui',{...ui,busy_enter_action:event.target.value})}><option value="follow_up">加入后续任务</option><option value="steer">立即补充指令</option><option value="draft">保留草稿</option></Select></Field><Advanced title="TUI 外观" note="终端界面独立主题"><Field label="TUI 主题" note="WebUI 主题在“外观”中设置"><Select value={ui.theme||'dark'} onChange={event=>edit('ui',{...ui,theme:event.target.value})}><option value="light">浅色</option><option value="dark">深色</option></Select></Field></Advanced></>}
            {section==='models'&&<SettingsModels config={models} onChange={value=>edit('models',value)} revision={entry?.revision||''} notify={notify}/>}
            {section==='runtime'&&<><Field label="默认工作阶段"><Select value={runtime.work_phase||'execute'} onChange={event=>edit('runtime',{...runtime,work_phase:event.target.value})}><option value="discuss">讨论</option><option value="plan">计划</option><option value="execute">执行</option></Select></Field><Field label="默认访问范围" note="讨论与计划阶段始终只读"><Select value={runtime.execution_access||'project'} onChange={event=>edit('runtime',{...runtime,execution_access:event.target.value})}><option value="project">项目访问</option><option value="full">完全访问</option></Select></Field><Advanced title="循环与续写限制"><div className="field-grid numeric-settings">{Object.entries(RUNTIME_LABELS).map(([name,label])=><Field label={label as string} key={name}><Numeric min={1} value={runtime[name]} onChange={item=>edit('runtime',{...runtime,[name]:item})}/></Field>)}</div></Advanced><Advanced title="实验能力"><Field label="实验性 MCP 工具追加"><input type="checkbox" checked={!!runtime.experimental_mcp_tool_append} onChange={event=>edit('runtime',{...runtime,experimental_mcp_tool_append:event.target.checked})}/></Field></Advanced></>}
            {section==='execution'&&<><div className="field-grid numeric-settings">{Object.entries(LIMIT_LABELS).filter(([name])=>['max_concurrency','max_processes'].includes(name)).map(([name,label])=><Field key={name} label={label as string}><Numeric min={0} value={execution.limits?.[name]} onChange={item=>edit('execution',{...execution,limits:{...execution.limits,[name]:item}})}/></Field>)}</div><Advanced title="会话资源、输出与超时"><div className="field-grid numeric-settings">{Object.entries(LIMIT_LABELS).filter(([name])=>!['max_concurrency','max_processes'].includes(name)).map(([name,label])=><Field key={name} label={label as string}><Numeric min={0} value={execution.limits?.[name]} onChange={item=>edit('execution',{...execution,limits:{...execution.limits,[name]:item}})}/></Field>)}</div></Advanced><Advanced title="命令资源约定" note="完整结构编辑"><JsonEditor label="命令资源配置" value={execution.command_profiles||[]} onChange={command_profiles=>edit('execution',{...execution,command_profiles})} draft={store.getEditor(keyFor('execution'),'command_profiles')} onDraft={value=>store.setEditor(keyFor('execution'),'command_profiles',value)} note="命令资源与就绪条件，修改时保留完整结构。"/></Advanced></>}
            {section==='mcp'&&<McpEditor value={mcp} onChange={value=>store.edit(keyFor('mcp',effectiveMcpScope),value)}/>}
            {section==='rules'&&<RulesEditor value={rules} onChange={value=>store.edit(keyFor('rules',effectiveRulesScope),value)}/>}
            {section==='storage'&&<SettingsStorage chats={chats} projects={projects} onOpenArchived={onOpenArchived} onRestoreArchived={onRestoreArchived} notify={notify}/>}
          </>}
        </div>
        {section!=='about'&&<footer className="settings-footer"><div><span>{scopeLabel}</span>{!readOnly&&<small>{conflict?'草稿已保留，重新读取当前页后可保存':dirty?'未保存修改，仅提交当前页面与配置层':savedState}</small>}</div>{!readOnly&&<div className="settings-save-actions">{dirty&&<button className="text-button" disabled={saving||loading} onClick={()=>void reloadCurrent()}>放弃当前页修改</button>}<button className="primary-button" disabled={!dirty||saving||loading||conflict||!!entry?.invalidEditors.length} onClick={()=>void save()}>{saving?<Spinner/>:<Icon name="check" size={15}/>}保存修改</button></div>}</footer>}
      </div>
    </div>
  </section>;
}
