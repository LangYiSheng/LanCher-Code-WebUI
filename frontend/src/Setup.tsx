import {useEffect,useRef,useState} from 'react';
import type {Dict} from './types';
import {api,ApiError,patch,readLocal,writeLocal} from './api';
import {desktopApi,isDesktop} from './desktopHost';
import {Brand} from './Brand';
import {Icon,Spinner} from './Icon';
import {Select} from './Select';
import {Modal,useDialogs} from './Dialogs';
import {Field} from './SettingsFields';
import {ProviderConnectionFields,ProviderCreateDialog} from './EntityForms';
import {entityText,generateEntityId,isValidEntityId,validateProvider,validateModel} from './entityValidation';
import {ProviderFields} from './SettingsModels';
import {UiFields,RuntimeFields,ExecutionFields} from './ConfigurationFields';
import {SetupModelPicker,SetupStory} from './SetupExperience';
import type {DiscoveryResult} from './discovery';
import type {SettingsEditorDraft} from './settingsDrafts';
import {ValidationProvider,ValidationScope,ValidationSummary,focusValidationIssue,normalizeValidationIssues,type ValidationIssue} from './settingsValidation';
import {chooseOnlyModel,initialSetupPage,issueStep,setupModelChoices,setupSteps,type SetupData,type SetupSnapshot,type SetupPage,type SetupStep} from './setupState';
import './Settings.css';
import './Setup.css';

const newProvider=():Dict=>({name:'',protocol:'',base_url:'',api_key:'',models:{},timeout_seconds:60,api_mode:'auto'});
const titles:Record<SetupPage,string>={welcome:'你好。',story:'把想法，变成现实。',source:'让我们开始。',imported:'你的模型，已经在这里。',connection:'连接你的供应商',models:'选择你的模型',ui:'调整显示设置',runtime:'调整运行设置',execution:'调整执行设置',review:'准备好开始了。'};
type ConnectionTest={state:'idle'|'running'|'success'|'failed';message:string};
export function Setup({onComplete,reloadKey=0,importRequest=0}:{onComplete:(startFirst?:boolean)=>Promise<boolean>;reloadKey?:number;importRequest?:number}){
  const dialogs=useDialogs(),desktop=isDesktop();
  const [snapshot,setSnapshot]=useState<SetupSnapshot|null>(null),[draft,setDraft]=useState<SetupData|null>(null),[step,setStep]=useState<SetupPage>('source');
  const [loading,setLoading]=useState(true),[pending,setPending]=useState(false),[error,setError]=useState(''),[notice,setNotice]=useState(''),[issues,setIssues]=useState<ValidationIssue[]>([]);
  const [steps,setSteps]=useState<SetupStep[]>(['connection','models','review']),[introShown,setIntroShown]=useState(false);
  const [providerId,setProviderId]=useState(''),[connection,setConnection]=useState<Dict>(newProvider),[customId,setCustomId]=useState<string|null>(null),[creating,setCreating]=useState(false),[connectionOptions,setConnectionOptions]=useState(false),[issueList,setIssueList]=useState(false);
  const [manual,setManual]=useState<Dict>({model_name:'',display_name:''}),[focusedIssue,setFocusedIssue]=useState<ValidationIssue|null>(null),[executionEditor,setExecutionEditor]=useState<SettingsEditorDraft>();
  const [changedDomains,setChangedDomains]=useState(new Set<string>()),[saved,setSaved]=useState(false),[test,setTest]=useState<ConnectionTest>({state:'idle',message:''});
  const generation=useRef(0),controller=useRef<AbortController|null>(null),testController=useRef<AbortController|null>(null),testGeneration=useRef(0),mounted=useRef(true),stage=useRef<HTMLDivElement>(null);
  const models=draft?.models||{providers:{},default_model:''},providers:Dict=models.providers||{},choices=setupModelChoices(models);
  const connectionDraft=providerId?providers[providerId]||connection:connection;
  const generatedId=generateEntityId(entityText(connection.name),Object.keys(providers),'provider'),nextId=(customId??generatedId).trim();
  const position=steps.indexOf(step as SetupStep),testing=test.state==='running';
  const selected=choices.find(choice=>choice.id===models.default_model),busy=pending||loading;

  function invalidateTest(){testGeneration.current++;testController.current?.abort();setTest({state:'idle',message:''});}
  function go(page:SetupPage){if(step==='review'&&page!=='review'){testGeneration.current++;testController.current?.abort();if(testing)setTest({state:'idle',message:''});}setStep(page);setFocusedIssue(null);setNotice('');setError('');}
  function acceptSnapshot(data:SetupSnapshot){
    const copy=data.data?structuredClone(data.data):null;if(copy)copy.models=chooseOnlyModel(copy.models);
    const automaticDefault=!!copy&&copy.models.default_model!==data.data?.models.default_model;
    setSnapshot(data);setDraft(copy);
    setIssues((data.issues||[]).filter(item=>!(item.domain==='models'&&item.path[0]==='default_model'&&(automaticDefault||data.state==='required'))&&(data.state!=='required'||item.domain!=='models'||item.path[0]!=='providers'||item.path.length>1)));
    setProviderId(Object.keys(data.data?.models.providers||{})[0]||'');setSteps(setupSteps(data.issues||[]));setConnection(newProvider());setCustomId(null);setManual({model_name:'',display_name:''});setChangedDomains(new Set(automaticDefault?['models']:[]));setExecutionEditor(undefined);setSaved(false);setFocusedIssue(null);setConnectionOptions(false);setIssueList(false);invalidateTest();
  }
  async function load(){
    controller.current?.abort();const abort=new AbortController();controller.current=abort;const token=++generation.current;
    setLoading(true);setPending(false);setError('');setNotice('');invalidateTest();
    try{
      const data=await api<SetupSnapshot>('/api/settings?domain=setup',{signal:abort.signal});
      if(abort.signal.aborted||token!==generation.current||!mounted.current)return;
      const page=data.state==='ready'?'imported':initialSetupPage(data,readLocal('setup-intro-seen',false));acceptSnapshot(data);setStep(page);setIntroShown(page==='welcome');
    }catch(reason){if(!abort.signal.aborted&&token===generation.current&&mounted.current)setError(reason instanceof Error?reason.message:String(reason));}
    finally{if(!abort.signal.aborted&&token===generation.current&&mounted.current)setLoading(false);}
  }
  useEffect(()=>{mounted.current=true;void load();return()=>{mounted.current=false;generation.current++;controller.current?.abort();testGeneration.current++;testController.current?.abort();};},[reloadKey]);
  const handledImport=useRef(0);
  useEffect(()=>{if(importRequest>handledImport.current&&!busy){handledImport.current=importRequest;void importConfiguration();}},[importRequest,busy]);
  useEffect(()=>{if(loading)return;const frame=requestAnimationFrame(()=>stage.current?.querySelector<HTMLElement>('h1')?.focus());return()=>cancelAnimationFrame(frame);},[step,loading]);
  useEffect(()=>{if(focusedIssue)focusValidationIssue(focusedIssue);},[focusedIssue,step,providerId,connectionOptions]);

  function edit(domain:keyof SetupData,value:Dict){
    if(!draft)return;
    setDraft(previous=>previous?{...previous,[domain]:domain==='models'?chooseOnlyModel(value):value}:previous);
    setChangedDomains(previous=>new Set([...previous,domain]));setError('');setNotice('');setSaved(false);invalidateTest();
    setIssues(previous=>previous.filter(item=>{if(item.domain!==domain)return true;const read=(source:any)=>item.path.reduce((value:any,key)=>value?.[key],source);return JSON.stringify(read(draft[domain]))===JSON.stringify(read(value));}));
  }
  function changeConnection(value:Dict){
    if(providerId)edit('models',{...models,providers:{...providers,[providerId]:value}});
    else{
      setConnection(value);setError('');setSaved(false);invalidateTest();
      const updatedId=(customId??generateEntityId(entityText(value.name),Object.keys(providers),'provider')).trim();
      setIssues(previous=>previous.flatMap(item=>{if(item.domain!=='models'||item.path[1]!==nextId)return [item];const path=item.path.slice(2),read=(source:any)=>path.reduce((part:any,key)=>part?.[key],source);if(JSON.stringify(read(connection))!==JSON.stringify(read(value))||path[0]==='id'&&updatedId!==nextId)return [];return [{...item,path:['providers',updatedId,...path]}];}));
    }
  }
  function locate(item:ValidationIssue){
    const page=item.path[0]==='default_model'?'models':issueStep(item);setStep(page);setIssueList(false);setSteps(previous=>previous.includes(page)?previous:setupSteps([...issues,item]));
    if(typeof item.path[1]==='string'&&providers[item.path[1]])setProviderId(item.path[1]);
    if(page==='connection'&&['api_mode','timeout_seconds','id'].includes(String(item.path[2])))setConnectionOptions(true);
    setFocusedIssue({...item});
  }
  function showIssues(found:ValidationIssue[]){setIssues(previous=>[...previous.filter(item=>!found.some(next=>next.domain===item.domain&&JSON.stringify(next.path)===JSON.stringify(item.path))),...found]);if(found[0])locate(found[0]);}
  function continueStep(){
    if(!draft||pending)return;
    if(step==='connection'){
      let catalogue=providers;
      if(!providerId){
        const found=validateProvider(connection,['providers',nextId],'models',true);
        if(!isValidEntityId(nextId))found.push({domain:'models',path:['providers',nextId,'id'],message:'标识只能包含中文、字母、数字、下划线和短横线。'});
        if(Object.hasOwn(providers,nextId))found.push({domain:'models',path:['providers',nextId,'id'],message:'这个供应商标识已存在。'});
        if(found.length){showIssues(found);return;}
        catalogue={...providers,[nextId]:connection};edit('models',{...models,providers:catalogue});setProviderId(nextId);
      }
      const found=Object.entries(catalogue).flatMap(([id,value])=>validateProvider(value as Dict,['providers',id],'models'));
      if(found.length){showIssues(found);return;}
    }
    if(step==='models'){
      let next=models;
      if(!choices.length){
        const provider=providers[providerId];if(!provider){go('connection');return;}
        const id=generateEntityId(entityText(manual.model_name),Object.keys(provider.models||{}),'model'),found=validateModel(manual,['providers',providerId,'models',id]);
        if(found.length){showIssues(found);return;}
        next=chooseOnlyModel({...models,providers:{...providers,[providerId]:{...provider,models:{...provider.models,[id]:{...manual,model_name:entityText(manual.model_name).trim()}}}}});
      }
      const found=Object.entries(next.providers).flatMap(([id,source])=>Object.entries((source as Dict).models||{}).flatMap(([modelId,model])=>validateModel(model as Dict,['providers',id,'models',modelId])));
      if(!setupModelChoices(next).some(choice=>choice.id===next.default_model))found.push({domain:'models',path:['default_model'],message:'请选择默认模型。'});
      if(found.length){showIssues(found);return;}
      edit('models',next);
    }
    if(step==='execution'&&executionEditor?.valid===false){setError('请先修正命令资源配置的 JSON。');return;}
    go(steps[Math.min(position+1,steps.length-1)]);
  }
  async function importConfiguration(){
    if(!desktop||busy)return;
    if(Object.keys(providers).length||connection.name||connection.api_key){if(!await dialogs.confirm({title:'导入现有配置',message:'将现有 LanCher Code 模型配置复制到桌面版，替换当前模型配置和未保存输入。原 LanCher Code 配置保留。',confirmLabel:'导入配置'}))return;}
    const token=++generation.current;controller.current?.abort();invalidateTest();setPending(true);setError('');setNotice('');
    try{
      const result=await (await desktopApi()).import_config();if(!mounted.current||token!==generation.current)return;
      if(!result.imported){setStep('source');setError('没有找到现有配置，可以直接设置一个模型。');return;}
      const data=await api<SetupSnapshot>('/api/settings?domain=setup');if(!mounted.current||token!==generation.current)return;
      acceptSnapshot(data);writeLocal('setup-intro-seen',true);setStep('imported');
    }catch(reason){if(mounted.current&&token===generation.current)setError(reason instanceof Error?reason.message:String(reason));}
    finally{if(mounted.current&&token===generation.current)setPending(false);}
  }
  async function testConnection(){
    if(!selected||!snapshot||testing)return;
    const id=selected.id.slice(0,selected.id.indexOf('/')),provider=providers[id];
    const token=++testGeneration.current,abort=new AbortController();testController.current?.abort();testController.current=abort;setTest({state:'running',message:'正在联系供应商…'});setError('');
    try{
      const data=await api<DiscoveryResult>('/api/settings/model-discovery',{method:'POST',body:JSON.stringify({provider_id:id,provider,revision:snapshot.revision,refresh:true}),signal:abort.signal});
      if(abort.signal.aborted||token!==testGeneration.current||!mounted.current)return;
      setTest(data.stale?{state:'failed',message:'未能确认当前连接，可以返回检查，或稍后再试。'}:{state:'success',message:`供应商已响应，读取到 ${data.models.length} 个模型。`});
    }catch(reason){if(!abort.signal.aborted&&token===testGeneration.current&&mounted.current){setTest({state:'failed',message:reason instanceof Error?reason.message:String(reason)});if(reason instanceof ApiError){const found=normalizeValidationIssues(reason.data.issues);if(found.length)showIssues(found);}}}
  }
  async function finish(){
    if(!draft||!snapshot||pending)return;
    if(!selected){showIssues([{domain:'models',path:['default_model'],message:'请选择默认模型。'}]);return;}
    if(executionEditor?.valid===false){go('execution');setError('请先修正命令资源配置的 JSON。');return;}
    const token=generation.current;setPending(true);setError('');testGeneration.current++;testController.current?.abort();
    try{
      if(!saved&&snapshot.state!=='ready'||changedDomains.size){
        const data:Dict={models};for(const domain of ['ui','runtime','execution'] as const)if(changedDomains.has(domain))data[domain]=draft[domain];
        const response=await patch<{saved:boolean;snapshot:SetupSnapshot}>('/api/settings',{domain:'setup',scope:'global',revision:snapshot.revision,data});
        if(!mounted.current||token!==generation.current)return;
        if(!response.saved)throw new Error('服务端尚未确认保存，请重试。');
        setSaved(true);setChangedDomains(new Set());setSnapshot(response.snapshot);if(response.snapshot.data)setDraft(response.snapshot.data);setIssues(response.snapshot.issues||[]);
      }
      if(!mounted.current||token!==generation.current)return;
      writeLocal('setup-intro-seen',true);
      if(!await onComplete(true)&&mounted.current&&token===generation.current)setError('配置已保存，工作台尚未就绪，请重试。');
    }catch(reason){if(!mounted.current||token!==generation.current)return;setError(reason instanceof Error?reason.message:String(reason));if(reason instanceof ApiError){const found=normalizeValidationIssues(reason.data.issues);setIssues(found);if(found[0])locate(found[0]);}}
    finally{if(mounted.current&&token===generation.current)setPending(false);}
  }
  async function reload(){if(changedDomains.size||connection.name||connection.api_key){if(!await dialogs.confirm({title:'重新读取配置',message:'当前填写的内容将被丢弃，重新读取磁盘上的配置。',confirmLabel:'重新读取'}))return;}await load();}
  function back(){if(step==='story')go('welcome');else if(step==='source')go('story');else if(step==='connection'||step==='imported')go('source');else go(steps[Math.max(0,position-1)]);}
  const intro=step==='welcome'||step==='story',unreadable=!loading&&!draft;
  const canBack=!loading&&step!=='welcome'&&(step!=='source'||introShown);
  const description=step==='welcome'?'欢迎来到 LanCher Code。':step==='story'?'和你一起读代码、做修改、把问题解决。':step==='source'?(unreadable?'现有配置暂时无法读取。':'接上你的模型，就可以开始工作。'):step==='connection'?'按供应商提供的信息填写。':step==='models'?'从一个模型开始，之后随时可以添加。':step==='imported'?'原来的连接与密钥已经保留。':step==='review'?'连接你的模型，开始第一段对话。':'修正这些现有参数后，就可以继续。';
  return <main className="setup-page settings-redesign">
    <header className="setup-topbar"><div><Brand size={24}/><span>LanCher Code</span></div>{!loading&&<button type="button" className="icon-button" aria-label="重新读取配置" title="重新读取配置" disabled={pending} onClick={()=>void reload()}><Icon name="refresh" size={15}/></button>}</header>
    <div className={'setup-stage '+(intro?'setup-stage-intro':'')} ref={stage}>
      {loading?<div className="setup-loading" role="status"><Spinner/><p>正在准备你的工作台…</p></div>:<section className={'setup-screen setup-screen-'+step} key={step}>
        {step==='welcome'&&<div className="setup-welcome-mark" aria-hidden="true"><span/><Brand size={86}/><span/></div>}
        <div className="setup-heading"><h1 tabIndex={-1}>{unreadable?'先把配置找回来。':titles[step]}</h1><p>{description}</p></div>
        {error&&<p className="setup-alert" role="alert">{error}</p>}
        {!intro&&step!=='source'&&step!=='imported'&&issues.length>0&&<button type="button" className="setup-issue-link" onClick={()=>setIssueList(true)}><Icon name="info" size={14}/>{issues.length} 项需要检查<Icon name="chevron" size={13}/></button>}
        {notice&&<p className="setup-hint" role="status">{notice}</p>}
        {step==='story'&&<SetupStory/>}
        {step==='source'&&<div className="setup-source-options">{desktop&&<button type="button" className="setup-source-option" disabled={busy} onClick={()=>void importConfiguration()}><span className="setup-symbol"><Icon name="copy" size={24}/></span><div><strong>从 LanCher Code 导入</strong><span>沿用已有供应商、模型和密钥</span></div><Icon name="chevron" size={17}/></button>}<button type="button" className="setup-source-option" disabled={busy||unreadable} onClick={()=>{writeLocal('setup-intro-seen',true);go('connection');}}><span className="setup-symbol"><Icon name="plus" size={24}/></span><div><strong>{desktop?'重新设置配置':'设置模型'}</strong><span>连接供应商，选择你的第一个模型</span></div><Icon name="chevron" size={17}/></button>{!unreadable&&<p className="setup-hint">{desktop?'导入会复制模型配置，原配置保持原样。':'WebUI 与 LanCher Code 共用此位置的模型配置。'}</p>}</div>}
        {unreadable&&<div className="setup-unreadable"><code>{snapshot?.config_path}</code><p>{[...new Set(issues.map(item=>item.message))].join(' ')||'请修复配置文件后重新读取，原文件会保留。'}</p><button type="button" className="secondary-button" disabled={busy} onClick={()=>void load()}><Icon name="refresh" size={14}/>重新读取</button></div>}
        {draft&&<fieldset className="setup-fields" disabled={pending}>
          {step==='connection'&&<ValidationProvider domain="models" issues={issues}>{Object.keys(providers).length>1&&<Field label="供应商"><Select value={providerId} onChange={event=>{setProviderId(event.target.value);setFocusedIssue(null);}}>{Object.entries(providers).map(([id,item])=><option key={id} value={id}>{entityText((item as Dict).name)||id}</option>)}</Select></Field>}<ValidationScope path={['providers',providerId||nextId]}><ProviderConnectionFields compact value={connectionDraft} onChange={changeConnection}/></ValidationScope><div className="setup-connection-links"><button type="button" className="text-button" onClick={()=>setConnectionOptions(true)}>连接选项</button>{Object.keys(providers).length>0&&<button type="button" className="text-button" onClick={()=>setCreating(true)}>添加其他供应商</button>}</div></ValidationProvider>}
          {step==='models'&&<SetupModelPicker models={models} providerId={providerId} onProvider={setProviderId} onChange={value=>edit('models',value)} manual={manual} onManual={value=>{setManual(value);setIssues(previous=>previous.filter(item=>item.path[2]!=='models'||providers[item.path[1]]?.models?.[item.path[3]]));setError('');}} revision={snapshot?.revision||''} issues={issues} focusedIssue={focusedIssue} onIssue={item=>showIssues([item])} notify={setNotice}/>}
          {step==='ui'&&<div className="setup-repair-fields"><ValidationProvider domain="ui" issues={issues}><UiFields value={draft.ui} onChange={value=>edit('ui',value)}/></ValidationProvider></div>}
          {step==='runtime'&&<div className="setup-repair-fields"><ValidationProvider domain="runtime" issues={issues}><RuntimeFields value={draft.runtime} onChange={value=>edit('runtime',value)}/></ValidationProvider></div>}
          {step==='execution'&&<div className="setup-repair-fields"><ValidationProvider domain="execution" issues={issues}><ExecutionFields value={draft.execution} onChange={value=>edit('execution',value)} editor={executionEditor} onEditor={setExecutionEditor}/></ValidationProvider></div>}
          {step==='imported'&&<div className="setup-import-preview"><div className="setup-import-icon"><Icon name="check" size={34}/></div><div className="setup-config-counts"><div><strong>{Object.keys(providers).length}</strong><span>供应商</span></div><div><strong>{choices.length}</strong><span>模型</span></div></div><div className="setup-import-default"><Icon name="spark" size={17}/><span>{selected?'默认模型 · '+selected.name:'还需要选择一个默认模型'}</span></div>{snapshot?.state!=='ready'&&<p className="setup-hint">有些配置需要补充，继续即可检查。</p>}</div>}
          {step==='review'&&<div className="setup-ready"><div className={'setup-ready-mark '+test.state}>{testing?<Spinner/>:<Icon name={test.state==='success'?'check':'link'} size={36}/>}</div><strong>{selected?.name}</strong><span>{selected?.provider}</span><div className="setup-test-status" role="status">{test.message||'可以先确认供应商连接，也可以稍后在设置中测试。'}</div><button type="button" className="secondary-button" disabled={pending} onClick={()=>{if(testing){invalidateTest();}else void testConnection();}}>{testing?'取消测试':test.state==='idle'?'测试连接':'重新测试'}</button><p className="setup-hint">仅查询模型目录，不发送对话。{test.state==='success'?'实际模型调用以对话结果为准。':''}</p></div>}
        </fieldset>}
      </section>}
    </div>
    <footer className="setup-footer"><div className="setup-footer-side">{canBack&&<button type="button" className="setup-back" disabled={busy} onClick={back}><Icon name="back" size={16}/>返回</button>}</div><div className="setup-footer-center">{!loading&&(intro?<button type="button" className="primary-button setup-continue" onClick={()=>{if(step==='welcome')go('story');else{writeLocal('setup-intro-seen',true);go('source');}}}>继续<Icon name="forward" size={15}/></button>:step==='imported'?<button type="button" className="primary-button setup-continue" disabled={pending} onClick={()=>{if(snapshot?.state==='ready')void finish();else go('connection');}}>{pending?<Spinner/>:<Icon name="forward" size={15}/>} {snapshot?.state==='ready'?'开始第一个对话':'继续设置'}</button>:step==='review'?<><button type="button" className="primary-button setup-continue" disabled={pending||testing} onClick={()=>void finish()}>{pending?<Spinner/>:<Icon name="forward" size={15}/>}开始第一个对话</button>{test.state==='idle'||test.state==='failed'?<span className="setup-footer-note">可以跳过测试，直接开始</span>:null}</>:step!=='source'&&!unreadable?<button type="button" className="primary-button setup-continue" disabled={pending} onClick={continueStep}>继续<Icon name="forward" size={15}/></button>:null)}<div className="setup-dots" aria-hidden="true">{(intro?['welcome','story','source']:step==='source'||step==='imported'?[]:steps).map(item=><i key={item} className={item===step?'active':''}/>)}</div></div><div className="setup-footer-side"/></footer>
    {creating&&<ProviderCreateDialog existing={providers} onClose={()=>setCreating(false)} onCreate={(id,value)=>{edit('models',{...models,providers:{...providers,[id]:value}});setProviderId(id);setCreating(false);}}/>}
    {connectionOptions&&<Modal title="连接选项" onClose={()=>setConnectionOptions(false)} className="settings-redesign entity-create-modal"><ValidationProvider domain="models" issues={issues}><ValidationScope path={['providers',providerId||nextId]}><ProviderFields value={connectionDraft} onChange={changeConnection}/>{!providerId&&<Field label="内部标识" path="id"><input value={customId??generatedId} onChange={event=>{setCustomId(event.target.value);setIssues(previous=>previous.filter(item=>item.path[2]!=='id'));}}/></Field>}</ValidationScope></ValidationProvider><div className="modal-footer"><button type="button" className="primary-button" onClick={()=>setConnectionOptions(false)}>完成</button></div></Modal>}
    {issueList&&<Modal title="需要检查的设置" onClose={()=>setIssueList(false)}><ValidationSummary issues={issues} onSelect={locate}/></Modal>}
  </main>;
}
