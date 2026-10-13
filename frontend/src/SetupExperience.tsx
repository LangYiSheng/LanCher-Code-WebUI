import {useEffect,useState} from 'react';
import type {Dict} from './types';
import {Brand} from './Brand';
import {Icon} from './Icon';
import {Select} from './Select';
import {Modal,useDialogs} from './Dialogs';
import {Field} from './SettingsFields';
import {ModelFields} from './SettingsModels';
import {ModelCreateDialog} from './EntityForms';
import {ModelDiscovery} from './ModelDiscovery';
import {entityText,generateEntityId} from './entityValidation';
import {chooseOnlyModel,setupModelChoices} from './setupState';
import {ValidationProvider,ValidationScope,focusValidationIssue,type ValidationIssue} from './settingsValidation';

// 与真实工作台相同的品牌、对话气泡和文件面板；动画只是功能演示。
export function SetupStory(){
  return <div className="setup-story" role="img" aria-label="功能演示：理解项目代码，修改搜索功能，运行测试并展示变更。">
    <div className="story-workbench" aria-hidden="true">
      <div className="story-window-bar"><Brand size={19}/><span>LanCher Code</span><i/><i/><i/></div>
      <div className="story-workspace"><aside className="story-sidebar"><span><Icon name="folder" size={14}/>我的项目</span><span className="story-file active"><Icon name="code" size={12}/>search.ts</span><span className="story-file"><Icon name="file" size={12}/>search.test.ts</span><div className="story-code"><i/><i/><i/><i/><i/><div className="story-diff"><span>+ filter(query)</span><span>+ render(results)</span></div></div></aside>
        <div className="story-chat"><div className="story-request">帮我给项目加一个搜索功能</div><div className="story-assistant"><Brand size={18}/><span>先看看项目，再把它实现。</span></div><div className="story-actions"><div className="story-action story-read"><Icon name="read" size={15}/><span>理解项目代码</span><Icon name="check" size={13}/></div><div className="story-action story-edit"><Icon name="edit" size={15}/><span>完成代码修改</span><Icon name="check" size={13}/></div><div className="story-action story-test"><Icon name="terminal" size={15}/><span>运行测试 · 全部通过</span><Icon name="check" size={13}/></div></div><div className="story-composer"><span>接下来，还想做什么？</span><Icon name="arrow" size={14}/></div></div>
      </div>
    </div><div className="story-caption" aria-hidden="true"><span>理解</span><i/><span>实现</span><i/><span>验证</span></div>
  </div>;
}

type ModelProps={models:Dict;providerId:string;onProvider:(id:string)=>void;onChange:(models:Dict)=>void;manual:Dict;onManual:(value:Dict)=>void;revision:string;issues:ValidationIssue[];focusedIssue:ValidationIssue|null;onIssue:(issue:ValidationIssue)=>void;notify:(text:string)=>void};
export function SetupModelPicker({models,providerId,onProvider,onChange,manual,onManual,revision,issues,focusedIssue,onIssue,notify}:ModelProps){
  const providers:Dict=models.providers||{},provider=providers[providerId],choices=setupModelChoices(models);
  const [discovering,setDiscovering]=useState(false),[creating,setCreating]=useState(false),[editing,setEditing]=useState<{providerId:string;modelId:string}|null>(null);
  const dialogs=useDialogs();
  const manualId=generateEntityId(entityText(manual.model_name),Object.keys(provider?.models||{}),'model');
  const defaultChoice=choices.find(item=>item.id===models.default_model);
  useEffect(()=>{
    if(!focusedIssue||focusedIssue.path[2]!=='models')return;
    const p=String(focusedIssue.path[1]),m=String(focusedIssue.path[3]);
    if(providers[p]?.models?.[m])setEditing({providerId:p,modelId:m});
  },[focusedIssue]);
  useEffect(()=>{if(editing)requestAnimationFrame(()=>{if(focusedIssue)focusValidationIssue(focusedIssue);});},[editing,focusedIssue]);
  function merge(value:Dict){onChange(chooseOnlyModel({...models,providers:{...providers,[providerId]:value}}));}
  const editedProvider=editing?providers[editing.providerId]:null,editedModel=editing?editedProvider?.models?.[editing.modelId]:null;
  return <ValidationProvider domain="models" issues={issues}>
    {Object.keys(providers).length>1&&<Field label="供应商"><Select value={providerId} onChange={event=>onProvider(event.target.value)}>{Object.entries(providers).map(([id,item])=><option key={id} value={id}>{entityText((item as Dict).name)||id}</option>)}</Select></Field>}
    {!choices.length?<ValidationScope path={['providers',providerId,'models',manualId]}><Field label="API 模型名称" path="model_name" required><input value={entityText(manual.model_name)} onChange={event=>onManual({...manual,model_name:event.target.value})} placeholder="例如 deepseek-chat" spellCheck={false}/></Field><Field label="显示名称" path="display_name"><input value={entityText(manual.display_name)} onChange={event=>onManual({...manual,display_name:event.target.value})} placeholder="可选，留空使用模型名称"/></Field></ValidationScope>:<>
      <div className="setup-selected-model"><span className="setup-symbol"><Icon name="spark" size={24}/></span><div><strong>{defaultChoice?.name||'选择你的模型'}</strong><span>{choices.length} 个模型可用 · 连接继承供应商</span></div>{defaultChoice&&<button type="button" className="icon-button" aria-label="编辑所选模型" onClick={()=>{const slash=defaultChoice.id.indexOf('/');setEditing({providerId:defaultChoice.id.slice(0,slash),modelId:defaultChoice.id.slice(slash+1)});}}><Icon name="edit" size={16}/></button>}</div>
      {(choices.length>1||!defaultChoice)&&<Field label="默认模型" path="default_model" required><Select value={entityText(models.default_model)} onChange={event=>onChange({...models,default_model:event.target.value})}><option value="">请选择默认模型</option>{choices.map(item=><option key={item.id} value={item.id}>{item.name} · {item.provider}</option>)}</Select></Field>}
    </>}
    <div className="setup-model-actions"><button type="button" className="secondary-button" disabled={!provider} onClick={()=>setDiscovering(true)}><Icon name="search" size={15}/>发现模型</button>{choices.length>0&&<button type="button" className="text-button" onClick={()=>setCreating(true)}><Icon name="plus" size={14}/>手动添加</button>}</div>
    <p className="setup-hint">{choices.length?'新对话会使用默认模型。':'使用供应商提供的实际模型名称，也可以从接口发现。'}</p>
    {discovering&&provider&&<ModelDiscovery providerId={providerId} provider={provider} revision={revision} onClose={()=>setDiscovering(false)} onValidationIssue={onIssue} onMerge={(value,added)=>{merge(value);setDiscovering(false);notify(added?`已添加 ${added} 个模型。`:'模型信息已更新。');}}/>}
    {creating&&provider&&<ModelCreateDialog existing={provider.models||{}} onClose={()=>setCreating(false)} onCreate={(id,value)=>{merge({...provider,models:{...provider.models,[id]:value}});setCreating(false);}}/>}
    {editing&&editedModel&&<Modal title="模型设置" onClose={()=>setEditing(null)} className="settings-redesign entity-create-modal"><ValidationScope path={['providers',editing.providerId,'models',editing.modelId]}><ModelFields value={editedModel} provider={editedProvider} onChange={value=>onChange({...models,providers:{...providers,[editing.providerId]:{...editedProvider,models:{...editedProvider.models,[editing.modelId]:value}}}})}/></ValidationScope><div className="modal-footer"><button type="button" className="text-button danger-text" onClick={()=>void dialogs.confirm({title:'移除模型',message:'将从待保存的目录中移除这个模型。',confirmLabel:'移除',danger:true}).then(confirmed=>{if(!confirmed)return;const remaining={...editedProvider.models};delete remaining[editing.modelId];onChange(chooseOnlyModel({...models,providers:{...providers,[editing.providerId]:{...editedProvider,models:remaining}}}));setEditing(null);})}>移除模型</button><button type="button" className="primary-button" onClick={()=>setEditing(null)}>完成</button></div></Modal>}
  </ValidationProvider>;
}
