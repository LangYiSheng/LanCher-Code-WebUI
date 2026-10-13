import {useEffect,useRef,useState} from 'react';
import type {ChatSummary,Dict,Preferences,Project} from './types';
import {api,patch} from './api';
import {Select} from './Select';
import {Icon,Spinner} from './Icon';
import {useDialogs} from './Dialogs';
import {Field} from './SettingsFields';
import {McpEditor} from './McpEditor';
import {UiFields,RuntimeFields,ExecutionFields} from './ConfigurationFields';
import {ValidationProvider,ValidationSummary,focusValidationIssue,validateModelsSettings,validateMcpSettings,type ValidationIssue} from './settingsValidation';
import {SettingsModels} from './SettingsModels';
import {SettingsStorage} from './SettingsStorage';
import {SettingsAbout} from './SettingsAbout';
import {useSettingsDrafts,type SettingsDraftStore,type SettingsDraftKey} from './settingsDrafts';
import './Settings.css';
function RulesEditor({value,onChange}:{value:Dict[];onChange:(value:Dict[])=>void}){return <><div className="editor-heading"><h3>持久拒绝规则</h3><button className="secondary-button" onClick={()=>onChange([...value,{match:'',result:'deny',match_kind:'exact'}])}><Icon name="plus" size={14}/>新增规则</button></div><p className="small-note">这些规则会持续拒绝匹配操作。普通操作授权通过聊天中的审批处理。</p>{value.map((rule,index)=>{const set=(key:string,item:any)=>onChange(value.map((x,i)=>i===index?{...x,[key]:item}:x));return <div className="rule-card" key={index}><div className="connection-settings"><Field label="匹配目标" path={[index,"match"]} required><input value={rule.match||''} onChange={e=>set('match',e.target.value)}/></Field><Field label="匹配方式" path={[index,"match_kind"]}><Select value={rule.match_kind||'exact'} onChange={e=>set('match_kind',e.target.value)}><option value="exact">精确匹配</option><option value="glob">Glob 模式</option></Select></Field><Field label="命令目录" path={[index,"command_cwd"]} note="可选"><input value={rule.command_cwd||''} onChange={e=>set('command_cwd',e.target.value||null)}/></Field><Field label="命令 Shell" path={[index,"command_shell"]} note="可选"><input value={rule.command_shell||''} onChange={e=>set('command_shell',e.target.value||null)}/></Field></div><button className="danger-text" onClick={()=>onChange(value.filter((_,i)=>i!==index))}>移除规则</button></div>;})}{!value.length&&<div className="panel-empty">这一层没有持久拒绝规则。</div>}</>;}

const GROUPS=[
  {label:'个人偏好',items:[['appearance','外观','sun'],['ui','输入与显示','chat']]},
  {label:'模型与能力',items:[['models','模型与供应商','globe'],['mcp','MCP 服务','mcp'],['rules','权限规则','shield']]},
  {label:'运行与数据',items:[['runtime','Agent 行为','spark'],['execution','执行与进程','terminal'],['storage','数据与历史','history'],['about','关于','info']]},
];
const DESCRIPTIONS:Record<string,string>={appearance:'设置 WebUI 外观。选择会实时预览，保存后保留。',ui:'调整显示与输入习惯，与 TUI 共用这些设置。',models:'管理连接和模型目录。新聊天采用默认模型，当前对话的模型选择保持不变。',mcp:'按配置层管理服务。项目中的同名服务覆盖全局配置。',rules:'持久规则会拒绝匹配的操作，对话中的审批仍在聊天内处理。',runtime:'设置工作阶段、访问范围与 Agent 的运行行为。',execution:'控制并发、进程和输出资源。保存后需重启服务应用。',storage:'查阅归档对话，管理浏览器输入草稿。',about:'查看前端发布版本与固定 SDK 来源。'};
type Props={drafts:SettingsDraftStore;project?:Project;preferences:Preferences;onPreview:(value:Preferences)=>void;onClose:()=>void;onSaved:()=>Promise<void>;notify:(text:string)=>void;initialSection?:string;chats:ChatSummary[];projects:Project[];onOpenArchived:(id:string)=>void;onRestoreArchived:(id:string)=>Promise<void>};
export function Settings({drafts:memory,project,preferences,onPreview,onClose,onSaved,notify,initialSection,chats,projects,onOpenArchived,onRestoreArchived}:Props){
  const store=useSettingsDrafts(memory),dialogs=useDialogs();
  const [section,setSection]=useState(initialSection&&DESCRIPTIONS[initialSection]?initialSection:'appearance');
  const [mcpScope,setMcpScope]=useState<'global'|'project'>('global'),[rulesScope,setRulesScope]=useState<'global'|'project'>('global');
  const [loading,setLoading]=useState(true),[loadErrors,setLoadErrors]=useState<Record<string,string>>({});
  const [focusedIssue,setFocusedIssue]=useState<ValidationIssue|null>(null);
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
  const issues=entry?.issues||[];
  const sourcePath=store.getSession(key.scope==='project'?key.projectId:undefined)?.snapshot.paths?.[key.domain==='mcp'?(key.scope==='project'?'project_mcp':'global_mcp'):key.domain==='rules'?(key.scope==='project'?'project_rules':'user_rules'):'config'];
  const displayedIssues=focusedIssue&&focusedIssue.domain===key.domain&&!issues.some(issue=>JSON.stringify(issue.path)===JSON.stringify(focusedIssue.path))?[...issues,focusedIssue]:issues;
  useEffect(()=>{if(focusedIssue)void focusValidationIssue(focusedIssue);},[focusedIssue,section,activeScope]);
  function locateIssue(issue:ValidationIssue){
    if(DESCRIPTIONS[issue.domain])setSection(issue.domain);
    setFocusedIssue({...issue});
  }
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
  function edit(name:string,value:Dict){setFocusedIssue(null);store.edit(keyFor(name),value);}
  function hasDirty(name:string){if(name==='storage'||name==='about')return false;if(['mcp','rules'].includes(name))return !!store.get(keyFor(name,'global'))?.dirty||!!project&&!!store.get(keyFor(name,'project'))?.dirty;return !!store.get(keyFor(name))?.dirty;}
  async function save(){
    if(readOnly||!dirty||saving||conflict||entry?.blocked)return;
    const found=section==='models'?validateModelsSettings(entry!.value):section==='mcp'?validateMcpSettings(entry!.value):[];
    if(found.length){store.setIssues(key,found);locateIssue(found[0]);return;}
    const sourceContext=project?.id;let ticket:ReturnType<SettingsDraftStore['beginSave']>;
    try{ticket=store.beginSave(key);}catch(reason){setLoadErrors(values=>({...values,[activeScope==='project'?'project':'global']:reason instanceof Error?reason.message:String(reason)}));return;}
    try{const response=await patch('/api/settings',ticket.payload);store.saved(ticket,response);notify('设置已保存。');}
    catch(reason){store.failed(ticket,reason);const first=store.get(ticket.key)?.issues[0];if(first)locateIssue(first);return;}
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
          <ValidationSummary issues={issues} onSelect={locateIssue}/>
          {section!=='about'&&(loadError||entry?.error)&&<div className="settings-error inline-error" role="alert"><span>{loadError||String(entry?.error)}</span><button className="text-button" disabled={saving} onClick={()=>void reloadCurrent()}>重新读取当前页</button></div>}
          {section!=='about'&&conflict&&!entry?.error&&<div className="settings-error inline-error" role="alert"><span>配置在其他界面发生变化。当前草稿已保留，请重新读取当前页后再保存。</span><button className="text-button" onClick={()=>void reloadCurrent()}>重新读取当前页</button></div>}
          {section==='about'?<SettingsAbout/>:loading?<div className="panel-empty"><Spinner/>正在读取配置…</div>:(!entry||entry.blocked)&&section!=='storage'?<div className="panel-empty">这页配置无法安全读取。请修复配置文件，再重新读取。{sourcePath&&<code className="settings-config-path">{sourcePath}</code>}<button className="text-button" onClick={()=>void reloadCurrent()}>重新读取</button></div>:<ValidationProvider domain={key.domain} issues={displayedIssues}>
            {section==='appearance'&&<><div className="settings-subheading"><div><h3>主题</h3><p>选择浅色、深色或跟随系统。</p></div></div><div className="theme-options">{[['light','浅色','sun'],['dark','深色','moon'],['system','跟随系统','monitor']].map(([name,label,icon])=><button className={prefs.theme===name?'selected':''} key={name} onClick={()=>store.edit(keyFor('appearance'),{...prefs,theme:name})}><span className={'theme-preview '+name}><i/><i/><i/></span><span><Icon name={icon} size={16}/>{label}{prefs.theme===name&&<Icon name="check" size={15}/>}</span></button>)}</div><Field label="减少透明效果" note="减少半透明遮罩与背景效果"><input type="checkbox" checked={!!prefs.reduce_transparency} onChange={event=>store.edit(keyFor('appearance'),{...prefs,reduce_transparency:event.target.checked})}/></Field><Field label="减少动画" note="关闭过渡与动画，也遵循操作系统偏好"><input type="checkbox" checked={prefs.reduce_motion} onChange={event=>store.edit(keyFor('appearance'),{...prefs,reduce_motion:event.target.checked})}/></Field></>}
            {section==='ui'&&<UiFields value={ui} onChange={value=>edit('ui',value)}/>}
            {section==='models'&&<SettingsModels config={models} onChange={value=>{setFocusedIssue(null);edit('models',value);}} revision={entry?.revision||''} notify={notify} issues={displayedIssues} focusedIssue={focusedIssue} onValidationIssue={issue=>{store.setIssues(key,[...issues,issue]);locateIssue(issue);}}/>}
            {section==='runtime'&&<RuntimeFields value={runtime} onChange={value=>edit('runtime',value)}/>}
            {section==='execution'&&<ExecutionFields value={execution} onChange={value=>edit('execution',value)} editor={store.getEditor(keyFor('execution'),'command_profiles')} onEditor={value=>store.setEditor(keyFor('execution'),'command_profiles',value)}/>}
            {section==='mcp'&&<McpEditor value={mcp} onChange={value=>{setFocusedIssue(null);store.edit(keyFor('mcp',effectiveMcpScope),value);}} issues={displayedIssues} focusedIssue={focusedIssue}/>}
            {section==='rules'&&<RulesEditor value={rules} onChange={value=>{setFocusedIssue(null);store.edit(keyFor('rules',effectiveRulesScope),value);}}/>}
            {section==='storage'&&<SettingsStorage chats={chats} projects={projects} onOpenArchived={onOpenArchived} onRestoreArchived={onRestoreArchived} notify={notify}/>}
          </ValidationProvider>}
        </div>
        {section!=='about'&&<footer className="settings-footer"><div><span>{scopeLabel}</span>{!readOnly&&<small>{conflict?'草稿已保留，重新读取当前页后可保存':dirty?'未保存修改，仅提交当前页面与配置层':savedState}</small>}</div>{!readOnly&&<div className="settings-save-actions">{dirty&&<button className="text-button" disabled={saving||loading} onClick={()=>void reloadCurrent()}>放弃当前页修改</button>}<button className="primary-button" disabled={!dirty||saving||loading||conflict||!!entry?.blocked||!!entry?.invalidEditors.length} onClick={()=>void save()}>{saving?<Spinner/>:<Icon name="check" size={15}/>}保存修改</button></div>}</footer>}
      </div>
    </div>
  </section>;
}
