import {useEffect,useState} from 'react';
import type {Dict} from './types';
import {Select} from './Select';
import {Icon} from './Icon';
import {useDialogs} from './Dialogs';
import {ModelDiscovery} from './ModelDiscovery';
import {API_MODES,capabilityList as rawCapabilityList} from './reasoning';
import {Field,Numeric,Advanced,SettingSource} from './SettingsFields';
import {ModelCreateDialog,ProviderConnectionFields,ProviderCreateDialog,protocolLabel} from './EntityForms';
import {ValidationScope,type ValidationIssue} from './settingsValidation';
import {entityText} from './entityValidation';

const protocolName=protocolLabel;
const modeName=(value:string)=>API_MODES.find(([key])=>key===value)?.[1]||value;
const capabilityList=(value:unknown,empty:string)=>rawCapabilityList(Array.isArray(value)?value.map(item=>entityText(item)).filter(Boolean):value,empty);
const providerTitle=(value:Dict,id:string)=>entityText(value.name)||id;
const modelTitle=(value:Dict,id:string|null)=>entityText(value.display_name)||entityText(value.model_name)||id||'模型';
export function ModelFields({value,onChange,provider}:{value:Dict;onChange:(value:Dict)=>void;provider:Dict}){
  const set=(key:string,item:any)=>onChange({...value,[key]:item});
  const metadata=value.metadata,cap=metadata?.capabilities||{},openai=(value.protocol||provider.protocol)==='openai';
  const inheritsKey=value.api_key_clear||!value.api_key_configured&&!value.api_key;
  return <>
    <div className="connection-settings">
      <Field path="model_name" label="API 模型名称" required><input value={entityText(value.model_name)} onChange={event=>set('model_name',event.target.value)} placeholder="例如 deepseek-chat"/></Field>
      <Field path="display_name" label="显示名称"><input value={entityText(value.display_name)} onChange={event=>set('display_name',event.target.value)} placeholder="可选"/></Field>
    </div>
    <Advanced title="连接覆盖" note="默认继承供应商">
      <div className="connection-settings">
        <Field path="protocol" label="调用协议"><Select value={entityText(value.protocol)} onChange={event=>set('protocol',event.target.value||null)}><option value="">继承供应商</option><option value="openai">OpenAI 兼容</option><option value="claude">Anthropic 兼容</option></Select><SettingSource label={value.protocol?'模型覆盖':'继承供应商'} value={protocolName(value.protocol||provider.protocol)}/></Field>
        {(openai||value.api_mode!=null&&!API_MODES.some(([key])=>key===value.api_mode))&&<Field path="api_mode" label="OpenAI 接口形式"><Select value={entityText(value.api_mode)} onChange={event=>set('api_mode',event.target.value||null)}><option value="">继承供应商</option>{API_MODES.map(([key,label])=><option key={key} value={key}>{label}</option>)}</Select><SettingSource label={value.api_mode?'模型覆盖':'继承供应商'} value={modeName(entityText(value.api_mode)||entityText(provider.api_mode)||'auto')}/></Field>}
        <Field path="base_url" label="Base URL"><input value={entityText(value.base_url)} onChange={event=>set('base_url',event.target.value||null)} placeholder="留空继承供应商"/><SettingSource label={value.base_url?'模型覆盖':'继承供应商'} value={entityText(value.base_url)||entityText(provider.base_url)||'尚未填写'}/></Field>
        <Field path="api_key" label="API Key" note={value.api_key_clear?'保存后恢复继承':value.api_key_configured?'已配置模型密钥，留空保留':'未配置模型覆盖'}><input type="password" autoComplete="new-password" value={value.api_key||''} placeholder="输入新的模型覆盖密钥" onChange={event=>onChange({...value,api_key:event.target.value,api_key_clear:false})}/><SettingSource label={inheritsKey?'继承供应商':'模型覆盖'} value={inheritsKey?(provider.api_key_clear?'供应商密钥待清除':provider.api_key||provider.api_key_configured?'已配置':'尚未配置'):value.api_key?'待保存新密钥':'已配置'}/><div className="field-subactions"><button type="button" className="text-button" onClick={()=>onChange({...value,api_key:null,api_key_clear:true})}>恢复继承</button></div></Field>
        <Field path="timeout_seconds" label="请求超时（秒）"><Numeric min={1} value={value.timeout_seconds} onChange={item=>set('timeout_seconds',item)} inherited placeholder="留空继承"/><SettingSource label={value.timeout_seconds==null?'继承供应商':'模型覆盖'} value={entityText(value.timeout_seconds??provider.timeout_seconds??60,'格式无效')}/></Field>
      </div>
    </Advanced>
    <Advanced title="容量与输出额度">
      <div className="field-grid numeric-settings">
        <Field path="context_window" label="上下文窗口"><Numeric min={1} value={value.context_window} onChange={item=>set('context_window',item)} placeholder="模型默认"/>{value.context_window==null&&metadata?.context_window&&<SettingSource label="端点快照声明" value={entityText(metadata.context_window,'格式无效')}/>}</Field>
        <Field path="max_output_tokens" label="总输出额度 tokens" note="思考、正文和工具参数共享上限"><Numeric min={1} value={value.max_output_tokens} onChange={item=>set('max_output_tokens',item)} placeholder="模型默认"/>{value.max_output_tokens==null&&metadata?.max_output_tokens&&<SettingSource label="端点快照上限" value={entityText(metadata.max_output_tokens,'格式无效')}/>}</Field>
      </div>
    </Advanced>
    <Advanced title="端点能力快照">
      <Field path="metadata" label="能力信息" note="无效或过期的快照可清除，连接与模型名称保持原样"><button type="button" className="secondary-button" disabled={metadata==null} onClick={()=>set('metadata',null)}>清除能力快照</button></Field>
      {metadata?<><dl className="data-list model-capability-list"><div><dt>API ID</dt><dd>{entityText(metadata.id,'未声明')}</dd></div><div><dt>归属</dt><dd>{entityText(metadata.owned_by,'未声明')||'未声明'}</dd></div><div><dt>窗口 / 总输出上限</dt><dd>{entityText(metadata.context_window,'未声明')} / {entityText(metadata.max_output_tokens,'未声明')}</dd></div><div><dt>推理档位</dt><dd>{capabilityList(cap.effort_levels,'不提供手动档位')}</dd></div><div><dt>默认档位</dt><dd>{entityText(cap.default_effort,'未声明')||'未声明'}</dd></div><div><dt>接口形式</dt><dd>{capabilityList(cap.endpoints,'未声明可用接口')}</dd></div><div><dt>思考类型</dt><dd>{capabilityList(cap.thinking_types,'未提供')}</dd></div><div><dt>输入 / 输出模态</dt><dd>{capabilityList(metadata.input_modalities,'未提供')} / {capabilityList(metadata.output_modalities,'未提供')}</dd></div><div><dt>获取时间</dt><dd>{typeof metadata.fetched_at==='string'?new Date(metadata.fetched_at).toLocaleString('zh-CN'):'未知'}</dd></div></dl><p className="small-note">连接或 API 模型名变化后需重新发现。实际可用档位以当前对话为准。</p></>:<p className="small-note">暂无能力信息，可通过“发现模型”获取。</p>}
    </Advanced>
  </>;
}
export function ProviderFields({value,onChange,creating=false}:{value:Dict;onChange:(value:Dict)=>void;creating?:boolean}){
  return <>
    <ProviderConnectionFields value={value} onChange={onChange} creating={creating}/>
    <Advanced title="接口与连接参数">
      {(value.protocol==='openai'||value.api_mode!==undefined&&!API_MODES.some(([key])=>key===value.api_mode))&&<Field path="api_mode" label="OpenAI 接口形式" note="自动按端点声明选择；未声明时采用兼容聊天"><Select value={entityText(value.api_mode)||'auto'} onChange={event=>onChange({...value,api_mode:event.target.value})}>{API_MODES.map(([key,label])=><option key={key} value={key}>{label}</option>)}</Select></Field>}
      <Field path="timeout_seconds" label="请求超时（秒）" required><Numeric min={1} value={value.timeout_seconds} onChange={item=>onChange({...value,timeout_seconds:item})}/></Field>
    </Advanced>
  </>;
}

type Selection={providerId:string;modelId:string|null};
export function SettingsModels({config,onChange,revision,notify,issues=[],focusedIssue,setupModelOnly=false,onValidationIssue}:{config:Dict;onChange:(value:Dict)=>void;revision:string;notify:(text:string)=>void;issues?:ValidationIssue[];focusedIssue?:ValidationIssue|null;setupModelOnly?:boolean;onValidationIssue?:(issue:ValidationIssue)=>void}){
  const {confirm}=useDialogs();const providers:Dict=config.providers||{};
  const [selection,setSelection]=useState<Selection>(()=>({providerId:Object.keys(providers)[0]||'',modelId:null}));
  const [collapsed,setCollapsed]=useState<string[]>([]),[query,setQuery]=useState(''),[discovering,setDiscovering]=useState(false),[creating,setCreating]=useState<'provider'|'model'|null>(null);
  const {providerId,modelId}=selection,provider=providers[providerId],model=modelId?provider?.models?.[modelId]:null;
  useEffect(()=>{if(!provider)setSelection({providerId:Object.keys(providers)[0]||'',modelId:null});else if(modelId&&!model)setSelection({providerId,modelId:null});},[providerId,modelId,providers]);
  useEffect(()=>{const issue=focusedIssue||issues[0],path=issue?.path;if(!path||path[0]!=='providers'||typeof path[1]!=='string'||!providers[path[1]])return;const id=path[1],item=path[2]==='models'&&typeof path[3]==='string'?path[3]:null;setSelection({providerId:id,modelId:item});setCollapsed(items=>items.filter(value=>value!==id));setQuery('');},[focusedIssue,issues]);
  const updateProvider=(value:Dict)=>onChange({...config,providers:{...providers,[providerId]:value}});
  const addProvider=()=>setCreating('provider');
  const addModel=()=>{if(provider)setCreating('model');};
  function addModels(value:Dict){const next:Dict={...config,providers:{...providers,[providerId]:value}};const references=Object.entries(next.providers).flatMap(([id,item])=>Object.keys((item as Dict).models||{}).map(key=>id+'/'+key));if(references.length===1)next.default_model=references[0];onChange(next);}
  async function deleteItem(){
    if(!provider)return;const target=modelId?'模型 '+modelId:'供应商 '+providerTitle(provider,providerId);
    if(!await confirm({title:'移除'+target,message:'从待保存的模型目录中移除'+target+(modelId?'。':'及其全部模型。')+'保存修改后生效。',confirmLabel:'移除',danger:true}))return;
    if(modelId){const models={...provider.models};delete models[modelId];updateProvider({...provider,models});setSelection({providerId,modelId:null});}
    else{const next={...providers};delete next[providerId];onChange({...config,providers:next});}
  }
  const needle=query.trim().toLowerCase();
  return <>
    {!setupModelOnly&&<div className="settings-default-model"><Field path="default_model" label="新聊天默认模型" note="不会改变当前对话的模型" required><Select value={entityText(config.default_model)} onChange={event=>onChange({...config,default_model:event.target.value})}><option value="">选择默认模型</option>{Object.entries(providers).flatMap(([p,source])=>Object.entries((source as Dict).models||{}).map(([id,item])=><option key={p+'/'+id} value={p+'/'+id}>{modelTitle(item as Dict,id)} · {providerTitle(source as Dict,p)}</option>))}</Select></Field></div>}
    <div className="settings-models-workspace">
      <section className="settings-model-directory" aria-label="供应商与模型目录">
        <div className="settings-directory-heading"><strong>供应商与模型</strong>{!setupModelOnly&&<button className="icon-button" aria-label="新增供应商" title="新增供应商" onClick={addProvider}><Icon name="plus" size={15}/></button>}</div>
        <div className="settings-directory-search"><Icon name="search" size={13}/><input aria-label="搜索模型目录" placeholder="搜索名称或 ID…" value={query} onChange={event=>setQuery(event.target.value)}/></div>
        <div className="settings-catalog">
          {Object.entries(providers).map(([id,item])=>{
            const source=item as Dict,providerMatch=!needle||(id+' '+entityText(source.name)).toLowerCase().includes(needle);
            const models=Object.entries(source.models||{}).filter(([key,value])=>providerMatch||(key+' '+entityText((value as Dict).display_name)+' '+entityText((value as Dict).model_name)).toLowerCase().includes(needle));
            if(!providerMatch&&!models.length)return null;const expanded=!!needle||!collapsed.includes(id);
            return <div className="settings-catalog-group" key={id}><div className="settings-provider-row">
              <button className="catalog-toggle icon-button" aria-label={(expanded?'收起':'展开')+'供应商 '+providerTitle(source,id)} aria-expanded={expanded} onClick={()=>setCollapsed(items=>expanded?[...items,id]:items.filter(key=>key!==id))}><Icon name="chevron" size={12} className={expanded?'expanded':''}/></button>
              <button className={'catalog-item '+(providerId===id&&modelId===null?'selected':'')} aria-pressed={providerId===id&&modelId===null} onClick={()=>setSelection({providerId:id,modelId:null})}><Icon name="globe" size={14}/><div className="catalog-provider-summary"><span>{providerTitle(source,id)}</span><small>{protocolName(source.protocol)}</small><small title={entityText(source.base_url)}>{entityText(source.base_url)||'尚未填写 Base URL'}</small></div><small>{Object.keys(source.models||{}).length}</small></button>
            </div>{expanded&&models.map(([key,item])=><button className={'catalog-model catalog-item '+(providerId===id&&modelId===key?'selected':'')} aria-pressed={providerId===id&&modelId===key} key={key} onClick={()=>setSelection({providerId:id,modelId:key})}><Icon name="spark" size={13}/><div><span>{modelTitle(item as Dict,key)}</span><small>{key}</small></div>{config.default_model===id+'/'+key&&<span className="catalog-default">默认</span>}</button>)}</div>;
          })}
          {!Object.keys(providers).length&&<p className="small-note">添加供应商后，可发现或手动添加模型。</p>}
        </div>{!setupModelOnly&&<button className="text-button catalog-add-provider" onClick={addProvider}><Icon name="plus" size={13}/>新增供应商</button>}
      </section>
      <section className="settings-model-detail" aria-label={model?'模型设置':'供应商设置'}>
        {provider?<><div className="settings-detail-heading"><div><span className="settings-detail-kind">{model?'模型':'供应商'}</span><h3>{model?modelTitle(model,modelId):providerTitle(provider,providerId)}</h3><code>{model?providerId+'/'+modelId:providerId}</code></div>{(!setupModelOnly||model)&&<button className="text-button danger-text" onClick={()=>void deleteItem()}>{model?'移除模型':'移除供应商'}</button>}</div>
          <div className="settings-model-actions">{model&&!setupModelOnly&&<button className="text-button" onClick={()=>setSelection({providerId,modelId:null})}><Icon name="globe" size={13}/>编辑供应商</button>}<button className="secondary-button" onClick={()=>setDiscovering(true)}><Icon name="search" size={14}/>发现模型</button><button className="secondary-button" onClick={addModel}><Icon name="plus" size={14}/>手动添加模型</button></div>
          {model?<><p className="settings-item-description">继承自 {providerTitle(provider,providerId)}</p><ValidationScope path={['providers',providerId,'models',modelId!]}><ModelFields key={providerId+'/'+modelId} value={model} provider={provider} onChange={value=>updateProvider({...provider,models:{...provider.models,[modelId!]:value}})}/></ValidationScope></>:setupModelOnly?<p className="settings-item-description">{protocolName(provider.protocol)} · {entityText(provider.base_url)}<br/>选择已有模型进行修复，或发现、手动添加 API 模型。</p>:<><ValidationScope path={['providers',providerId]}><ProviderFields key={providerId} value={provider} onChange={updateProvider}/></ValidationScope></>}
        </>:<div className="panel-empty"><Icon name="globe" size={28}/><p>选择一个供应商或模型开始编辑。</p></div>}
      </section>
    </div>
    {creating==='provider'&&<ProviderCreateDialog existing={providers} onClose={()=>setCreating(null)} onCreate={(id,value)=>{onChange({...config,providers:{...providers,[id]:value}});setSelection({providerId:id,modelId:null});setCreating(null);}}/>}
    {creating==='model'&&provider&&<ModelCreateDialog key={providerId} existing={provider.models||{}} onClose={()=>setCreating(null)} onCreate={(id,value)=>{addModels({...provider,models:{...provider.models,[id]:value}});setSelection({providerId,modelId:id});setCollapsed(items=>items.filter(item=>item!==providerId));setCreating(null);}}/>}
    {discovering&&provider&&<ModelDiscovery key={providerId} providerId={providerId} provider={provider} revision={revision} onClose={()=>setDiscovering(false)} onValidationIssue={onValidationIssue} onMerge={(merged,added,updated)=>{addModels(merged);setDiscovering(false);notify(`已加入 ${added} 个模型，更新 ${updated} 个能力快照；${setupModelOnly?'完成引导后':'保存修改后'}生效。`);}}/>}
  </>;
}
