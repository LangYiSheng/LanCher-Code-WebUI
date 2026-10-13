import {useEffect,useRef,useState} from 'react';
import type {Dict} from './types';
import {Modal} from './Dialogs';
import {Select} from './Select';
import {Icon} from './Icon';
import {Advanced,Field,SettingSource} from './SettingsFields';
import {ValidationProvider,focusValidationIssue,type ValidationIssue} from './settingsValidation';
import {entityText,generateEntityId,isValidEntityId,validateModel,validateProviderConnection} from './entityValidation';
import './EntityForms.css';

export const protocolLabel=(value:string)=>value==='claude'?'Anthropic 兼容':value==='openai'?'OpenAI 兼容':'尚未选择协议';
export function ProviderConnectionFields({value,onChange,creating=false,compact=false}:{value:Dict;onChange:(value:Dict)=>void;creating?:boolean;compact?:boolean}){
  const set=(key:string,item:any)=>onChange({...value,[key]:item});
  return <div className="connection-settings">
    <Field path="name" label="供应商名称" note={compact?undefined:'在模型目录中显示，例如我的 DeepSeek'} required><input autoFocus={creating} value={entityText(value.name)} onChange={event=>set('name',event.target.value)} placeholder="例如 DeepSeek"/></Field>
    <Field path="protocol" label="调用协议" note={compact?undefined:'按供应商的 API 文档选择；地址相似也可能使用不同协议'} required><Select value={entityText(value.protocol)} onChange={event=>set('protocol',event.target.value)}><option value="" disabled>请选择调用协议</option><option value="openai">OpenAI 兼容</option><option value="claude">Anthropic 兼容</option></Select></Field>
    <Field path="base_url" label="Base URL" note={compact?undefined:'填写该协议的 API 基址，包含服务要求的路径'} required><input value={entityText(value.base_url)} onChange={event=>set('base_url',event.target.value)} placeholder={value.protocol==='claude'?'例如 https://api.anthropic.com':'例如 https://api.example.com/v1'} spellCheck={false} inputMode="url"/></Field>
    <Field path="api_key" label="API Key" note={compact?undefined:value.api_key_configured&&!value.api_key_clear?'已配置，留空保留已有密钥':'填写供应商提供的 API Key，保存后供模型调用'} required><input type="password" autoComplete="new-password" value={value.api_key||''} onChange={event=>onChange({...value,api_key:event.target.value,api_key_clear:false})} placeholder={value.api_key_configured?'留空保留已有密钥':'请输入 API Key'}/>{!compact&&value.api_key_configured&&<SettingSource label="密钥状态" value="已配置"/>}</Field>
  </div>;
}
function useCreationIssues(){
  const [issues,setIssues]=useState<ValidationIssue[]>([]);const form=useRef<HTMLFormElement>(null);
  useEffect(()=>{const frame=requestAnimationFrame(()=>form.current?.querySelector<HTMLInputElement>('input')?.focus());return()=>cancelAnimationFrame(frame);},[]);
  const validate=(next:ValidationIssue[])=>{setIssues(next);if(next.length){requestAnimationFrame(()=>focusValidationIssue(next[0],form.current||undefined));return false;}return true;};
  return {issues,setIssues,form,validate};
}
function unchangedIssues(issues:ValidationIssue[],before:Dict,after:Dict,derivedIdChanged=false){
  return issues.filter(item=>item.path[0]==='id'?!derivedIdChanged:Object.is(before[item.path[0]],after[item.path[0]]));
}
export function ProviderCreateDialog({existing,onClose,onCreate}:{existing:Dict;onClose:()=>void;onCreate:(id:string,value:Dict)=>void}){
  const [value,setValue]=useState<Dict>({name:'',protocol:'',base_url:'',api_key:'',timeout_seconds:60,api_mode:'auto',models:{}}),[customId,setCustomId]=useState<string|null>(null);
  const {issues,setIssues,form,validate}=useCreationIssues();const id=customId??generateEntityId(value.name||'provider',Object.keys(existing),'provider');
  function submit(){
    const next=validateProviderConnection(value,[],'models',true);
    if(!isValidEntityId(id))next.push({domain:'models',path:['id'],message:'ID 只能包含中文、字母、数字、下划线和短横线。'});
    else if(Object.hasOwn(existing,id))next.push({domain:'models',path:['id'],message:'这个供应商 ID 已存在。'});
    if(!validate(next))return;
    onCreate(id,{...value,name:value.name.trim(),base_url:value.base_url.trim()});
  }
  return <Modal title="新增供应商" subtitle="先填写可用连接，再发现或手动添加模型。" onClose={onClose} className="entity-create-modal settings-redesign">
    <form ref={form} noValidate onSubmit={event=>{event.preventDefault();submit();}}><ValidationProvider domain="models" issues={issues}>
      <ProviderConnectionFields creating value={value} onChange={next=>{setValue(next);setIssues(items=>unchangedIssues(items,value,next,customId===null&&value.name!==next.name));}}/>
      <Advanced title="内部 ID" note="自动生成，可按需修改"><Field path="id" label="供应商 ID" note="用于配置引用，创建后保持稳定" required><input value={id} maxLength={100} onChange={event=>{setCustomId(event.target.value);setIssues(items=>items.filter(item=>item.path[0]!=='id'));}}/><button type="button" className="text-button" onClick={()=>{setCustomId(null);setIssues(items=>items.filter(item=>item.path[0]!=='id'));}}>恢复自动生成</button></Field></Advanced>
      <div className="modal-footer"><button type="button" className="secondary-button" onClick={onClose}>取消</button><button type="submit" className="primary-button"><Icon name="plus" size={15}/>添加供应商</button></div>
    </ValidationProvider></form>
  </Modal>;
}
export function ModelCreateDialog({existing,onClose,onCreate}:{existing:Dict;onClose:()=>void;onCreate:(id:string,value:Dict)=>void}){
  const [value,setValue]=useState<Dict>({model_name:'',display_name:'',protocol:null,base_url:null,api_key:null,timeout_seconds:null,context_window:null,max_output_tokens:null,api_mode:null,metadata:null}),[customId,setCustomId]=useState<string|null>(null);
  const {issues,setIssues,form,validate}=useCreationIssues();const id=customId??generateEntityId(value.model_name||'model',Object.keys(existing),'model');
  function submit(){
    const next=validateModel(value);
    if(!isValidEntityId(id))next.push({domain:'models',path:['id'],message:'ID 只能包含中文、字母、数字、下划线和短横线。'});
    else if(Object.hasOwn(existing,id))next.push({domain:'models',path:['id'],message:'这个模型 ID 已存在。'});
    if(!validate(next))return;
    onCreate(id,{...value,model_name:value.model_name.trim(),display_name:value.display_name.trim()});
  }
  return <Modal title="手动添加模型" subtitle="填写 API 接受的实际模型名称；连接默认继承供应商。" onClose={onClose} className="entity-create-modal settings-redesign">
    <form ref={form} noValidate onSubmit={event=>{event.preventDefault();submit();}}><ValidationProvider domain="models" issues={issues}>
      <div className="connection-settings"><Field path="model_name" label="API 模型名称" note="发送给端点的实际模型 ID，可包含斜杠或点号" required><input autoFocus value={value.model_name} onChange={event=>{setValue({...value,model_name:event.target.value});setIssues(items=>items.filter(item=>item.path[0]!=='model_name'&&(customId!==null||item.path[0]!=='id')));}} placeholder="例如 deepseek-chat 或 org/model"/></Field><Field path="display_name" label="显示名称" note="可选，仅改变模型列表中的名称"><input value={value.display_name} onChange={event=>{setValue({...value,display_name:event.target.value});setIssues(items=>items.filter(item=>item.path[0]!=='display_name'));}} placeholder="例如日常编程模型"/></Field></div>
      <Advanced title="内部 ID" note="自动生成，可按需修改"><Field path="id" label="模型 ID" note="用于配置引用，API 名称不受此 ID 格式限制" required><input value={id} maxLength={100} onChange={event=>{setCustomId(event.target.value);setIssues(items=>items.filter(item=>item.path[0]!=='id'));}}/><button type="button" className="text-button" onClick={()=>{setCustomId(null);setIssues(items=>items.filter(item=>item.path[0]!=='id'));}}>恢复自动生成</button></Field></Advanced>
      <div className="modal-footer"><button type="button" className="secondary-button" onClick={onClose}>取消</button><button type="submit" className="primary-button"><Icon name="plus" size={15}/>添加模型</button></div>
    </ValidationProvider></form>
  </Modal>;
}
