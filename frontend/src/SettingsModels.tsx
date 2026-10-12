import {useEffect,useState} from 'react';
import type {Dict} from './types';
import {Select} from './Select';
import {Icon} from './Icon';
import {useDialogs} from './Dialogs';
import {ModelDiscovery} from './ModelDiscovery';
import {API_MODES,capabilityList} from './reasoning';
import {Field,Numeric,Advanced,SettingSource} from './SettingsFields';

const protocolName=(value:string)=>value==='claude'?'Claude':'OpenAI 兼容';
const modeName=(value:string)=>API_MODES.find(([key])=>key===value)?.[1]||value;
function ModelFields({value,onChange,provider}:{value:Dict;onChange:(value:Dict)=>void;provider:Dict}){
  const set=(key:string,item:any)=>onChange({...value,[key]:item});
  const metadata=value.metadata,cap=metadata?.capabilities||{},openai=(value.protocol||provider.protocol)==='openai';
  const inheritsKey=value.api_key_clear||!value.api_key_configured&&!value.api_key;
  return <>
    <div className="connection-settings">
      <Field label="API 模型名称" note="发送给端点的实际模型 ID"><input value={value.model_name||''} onChange={event=>set('model_name',event.target.value)} placeholder="例如 deepseek-chat" required/></Field>
      <Field label="显示名称" note="只影响模型列表中的名称"><input value={value.display_name||''} onChange={event=>set('display_name',event.target.value)} placeholder="可选"/></Field>
    </div>
    <Advanced title="连接覆盖" note="默认继承供应商">
      <div className="connection-settings">
        <Field label="调用协议"><Select value={value.protocol||''} onChange={event=>set('protocol',event.target.value||null)}><option value="">继承供应商</option><option value="openai">OpenAI 兼容</option><option value="claude">Claude</option></Select><SettingSource label={value.protocol?'模型覆盖':'继承供应商'} value={protocolName(value.protocol||provider.protocol)}/></Field>
        {openai&&<Field label="OpenAI 接口形式"><Select value={value.api_mode||''} onChange={event=>set('api_mode',event.target.value||null)}><option value="">继承供应商</option>{API_MODES.map(([key,label])=><option key={key} value={key}>{label}</option>)}</Select><SettingSource label={value.api_mode?'模型覆盖':'继承供应商'} value={modeName(value.api_mode||provider.api_mode||'auto')}/></Field>}
        <Field label="Base URL"><input value={value.base_url||''} onChange={event=>set('base_url',event.target.value||null)} placeholder="留空继承供应商"/><SettingSource label={value.base_url?'模型覆盖':'继承供应商'} value={value.base_url||provider.base_url||'尚未填写'}/></Field>
        <Field label="API Key" note={value.api_key_clear?'保存后恢复继承':value.api_key_configured?'已配置模型密钥，留空保留':'未配置模型覆盖'}><input type="password" autoComplete="new-password" value={value.api_key||''} placeholder="输入新的模型覆盖密钥" onChange={event=>onChange({...value,api_key:event.target.value,api_key_clear:false})}/><SettingSource label={inheritsKey?'继承供应商':'模型覆盖'} value={inheritsKey?(provider.api_key_clear?'供应商密钥待清除':provider.api_key||provider.api_key_configured?'已配置':'尚未配置'):value.api_key?'待保存新密钥':'已配置'}/><div className="field-subactions"><button className="text-button" onClick={()=>onChange({...value,api_key:null,api_key_clear:true})}>恢复继承</button></div></Field>
        <Field label="请求超时（秒）"><Numeric min={1} value={value.timeout_seconds} onChange={item=>set('timeout_seconds',item)} inherited placeholder="留空继承"/><SettingSource label={value.timeout_seconds==null?'继承供应商':'模型覆盖'} value={value.timeout_seconds??provider.timeout_seconds??60}/></Field>
      </div>
    </Advanced>
    <Advanced title="容量与输出额度" note="按模型默认值使用">
      <div className="field-grid numeric-settings">
        <Field label="上下文窗口" note={value.context_window==null?'未覆盖，采用模型默认':'独立模型覆盖'}><Numeric min={1} value={value.context_window} onChange={item=>set('context_window',item)} placeholder="模型默认"/>{value.context_window==null&&metadata?.context_window&&<SettingSource label="端点快照声明" value={metadata.context_window}/>}</Field>
        <Field label="总输出额度 tokens" note="思考、正文和工具参数共享上限"><Numeric min={1} value={value.max_output_tokens} onChange={item=>set('max_output_tokens',item)} placeholder="模型默认"/>{value.max_output_tokens==null&&metadata?.max_output_tokens&&<SettingSource label="端点快照上限" value={metadata.max_output_tokens}/>}</Field>
      </div><p className="small-note">留空不覆盖模型默认值。推理强度在当前对话的输入栏或 /effort 中调整。</p>
    </Advanced>
    <Advanced title="端点能力快照" note="只读信息">
      {metadata?<><dl className="data-list model-capability-list"><div><dt>API ID</dt><dd>{metadata.id}</dd></div><div><dt>归属</dt><dd>{metadata.owned_by||'未声明'}</dd></div><div><dt>窗口 / 总输出上限</dt><dd>{metadata.context_window?.toLocaleString('zh-CN')||'未声明'} / {metadata.max_output_tokens?.toLocaleString('zh-CN')||'未声明'}</dd></div><div><dt>推理档位</dt><dd>{capabilityList(cap.effort_levels,'不提供手动档位')}</dd></div><div><dt>默认档位</dt><dd>{cap.default_effort||'未声明'}</dd></div><div><dt>接口形式</dt><dd>{capabilityList(cap.endpoints,'未声明可用接口')}</dd></div><div><dt>思考类型</dt><dd>{capabilityList(cap.thinking_types,'未提供')}</dd></div><div><dt>输入 / 输出模态</dt><dd>{capabilityList(metadata.input_modalities,'未提供')} / {capabilityList(metadata.output_modalities,'未提供')}</dd></div><div><dt>获取时间</dt><dd>{metadata.fetched_at?new Date(metadata.fetched_at).toLocaleString('zh-CN'):'未知'}</dd></div></dl><p className="small-note">连接或 API 模型名变化后需重新发现。实际可用档位以当前对话为准。</p></>:<p className="small-note">尚未发现当前模型的能力信息。可使用“发现模型”查询端点，未知能力不会推测。</p>}
    </Advanced>
  </>;
}
function ProviderFields({value,onChange}:{value:Dict;onChange:(value:Dict)=>void}){
  return <>
    <div className="connection-settings">
      <Field label="供应商名称" note="在目录中显示"><input value={value.name||''} onChange={event=>onChange({...value,name:event.target.value})}/></Field>
      <Field label="Base URL" note="填写该协议的 API 基址"><input value={value.base_url||''} onChange={event=>onChange({...value,base_url:event.target.value})} placeholder="https://…"/></Field>
      <Field label="API Key" note={value.api_key_clear?'保存后清除已有密钥':value.api_key_configured?'已配置，留空保留':'尚未配置'}><input type="password" autoComplete="new-password" value={value.api_key||''} onChange={event=>onChange({...value,api_key:event.target.value,api_key_clear:false})} placeholder="输入新的密钥，留空保留"/><div className="field-subactions"><button className="text-button" onClick={()=>onChange({...value,api_key:'',api_key_clear:true})}>清除已有密钥</button></div></Field>
    </div>
    <Advanced title="接口与连接参数" note="协议、调用形式和超时">
      <Field label="调用协议"><Select value={value.protocol||'openai'} onChange={event=>onChange({...value,protocol:event.target.value})}><option value="openai">OpenAI 兼容</option><option value="claude">Claude</option></Select></Field>
      {value.protocol==='openai'&&<Field label="OpenAI 接口形式" note="自动按端点声明选择；未声明时采用兼容聊天"><Select value={value.api_mode||'auto'} onChange={event=>onChange({...value,api_mode:event.target.value})}>{API_MODES.map(([key,label])=><option key={key} value={key}>{label}</option>)}</Select></Field>}
      <Field label="请求超时（秒）"><Numeric min={1} value={value.timeout_seconds} onChange={item=>onChange({...value,timeout_seconds:item})}/></Field>
    </Advanced>
  </>;
}

type Selection={providerId:string;modelId:string|null};
export function SettingsModels({config,onChange,revision,notify}:{config:Dict;onChange:(value:Dict)=>void;revision:string;notify:(text:string)=>void}){
  const {prompt,confirm}=useDialogs();const providers:Dict=config.providers||{};
  const [selection,setSelection]=useState<Selection>(()=>({providerId:Object.keys(providers)[0]||'',modelId:null}));
  const [collapsed,setCollapsed]=useState<string[]>([]),[query,setQuery]=useState(''),[discovering,setDiscovering]=useState(false);
  const {providerId,modelId}=selection,provider=providers[providerId],model=modelId?provider?.models?.[modelId]:null;
  useEffect(()=>{if(!provider)setSelection({providerId:Object.keys(providers)[0]||'',modelId:null});else if(modelId&&!model)setSelection({providerId,modelId:null});},[providerId,modelId,providers]);
  const updateProvider=(value:Dict)=>onChange({...config,providers:{...providers,[providerId]:value}});
  function addProvider(){void prompt({title:'新增供应商',label:'供应商 ID',subtitle:'字母、数字、短横线或下划线；显示名称可稍后修改。',confirmLabel:'添加',maxLength:100,validate:id=>providers[id]?'这个供应商 ID 已存在。':!/^[A-Za-z0-9_-]+$/.test(id)?'ID 只能包含字母、数字、短横线或下划线。':undefined,onSubmit:id=>{onChange({...config,providers:{...providers,[id]:{name:id,protocol:'openai',base_url:'',api_key:'',timeout_seconds:60,api_mode:'auto',models:{}}}});setSelection({providerId:id,modelId:null});}});}
  function addModel(){if(!provider)return;void prompt({title:'新增模型',label:'模型 ID',subtitle:'用于目录引用，API 模型名称可稍后修改。',confirmLabel:'添加',maxLength:100,validate:id=>provider.models?.[id]?'这个模型 ID 已存在。':/[\s/\\]/.test(id)?'模型 ID 不能包含空白或斜杠。':undefined,onSubmit:id=>{updateProvider({...provider,models:{...provider.models,[id]:{model_name:id,display_name:'',protocol:null,base_url:null,api_key:null,timeout_seconds:null,context_window:null,max_output_tokens:null,api_mode:null,metadata:null}}});setSelection({providerId,modelId:id});setCollapsed(items=>items.filter(item=>item!==providerId));}});}
  async function deleteItem(){
    if(!provider)return;const target=modelId?'模型 '+modelId:'供应商 '+(provider.name||providerId);
    if(!await confirm({title:'移除'+target,message:'从待保存的模型目录中移除'+target+(modelId?'。':'及其全部模型。')+'保存修改后生效。',confirmLabel:'移除',danger:true}))return;
    if(modelId){const models={...provider.models};delete models[modelId];updateProvider({...provider,models});setSelection({providerId,modelId:null});}
    else{const next={...providers};delete next[providerId];onChange({...config,providers:next});}
  }
  const needle=query.trim().toLowerCase();
  return <>
    <div className="settings-default-model"><Field label="新聊天默认模型" note="不会改变当前对话的模型"><Select value={config.default_model||''} onChange={event=>onChange({...config,default_model:event.target.value})}><option value="">选择默认模型</option>{Object.entries(providers).flatMap(([p,source])=>Object.entries((source as Dict).models||{}).map(([id,item])=><option key={p+'/'+id} value={p+'/'+id}>{(item as Dict).display_name||(item as Dict).model_name||id} · {(source as Dict).name||p}</option>))}</Select></Field></div>
    <div className="settings-models-workspace">
      <section className="settings-model-directory" aria-label="供应商与模型目录">
        <div className="settings-directory-heading"><strong>供应商与模型</strong><button className="icon-button" aria-label="新增供应商" title="新增供应商" onClick={addProvider}><Icon name="plus" size={15}/></button></div>
        <div className="settings-directory-search"><Icon name="search" size={13}/><input aria-label="搜索模型目录" placeholder="搜索名称或 ID…" value={query} onChange={event=>setQuery(event.target.value)}/></div>
        <div className="settings-catalog">
          {Object.entries(providers).map(([id,item])=>{
            const source=item as Dict,providerMatch=!needle||(id+' '+source.name).toLowerCase().includes(needle);
            const models=Object.entries(source.models||{}).filter(([key,value])=>providerMatch||(key+' '+(value as Dict).display_name+' '+(value as Dict).model_name).toLowerCase().includes(needle));
            if(!providerMatch&&!models.length)return null;const expanded=!!needle||!collapsed.includes(id);
            return <div className="settings-catalog-group" key={id}><div className="settings-provider-row">
              <button className="catalog-toggle icon-button" aria-label={(expanded?'收起':'展开')+'供应商 '+(source.name||id)} aria-expanded={expanded} onClick={()=>setCollapsed(items=>expanded?[...items,id]:items.filter(key=>key!==id))}><Icon name="chevron" size={12} className={expanded?'expanded':''}/></button>
              <button className={'catalog-item '+(providerId===id&&modelId===null?'selected':'')} aria-pressed={providerId===id&&modelId===null} onClick={()=>setSelection({providerId:id,modelId:null})}><Icon name="globe" size={14}/><span>{source.name||id}</span><small>{Object.keys(source.models||{}).length}</small></button>
            </div>{expanded&&models.map(([key,item])=><button className={'catalog-model catalog-item '+(providerId===id&&modelId===key?'selected':'')} aria-pressed={providerId===id&&modelId===key} key={key} onClick={()=>setSelection({providerId:id,modelId:key})}><Icon name="spark" size={13}/><div><span>{(item as Dict).display_name||(item as Dict).model_name||key}</span><small>{key}</small></div>{config.default_model===id+'/'+key&&<span className="catalog-default">默认</span>}</button>)}</div>;
          })}
          {!Object.keys(providers).length&&<p className="small-note">添加供应商后，可发现或手动添加模型。</p>}
        </div><button className="text-button catalog-add-provider" onClick={addProvider}><Icon name="plus" size={13}/>新增供应商</button>
      </section>
      <section className="settings-model-detail" aria-label={model?'模型设置':'供应商设置'}>
        {provider?<><div className="settings-detail-heading"><div><span className="settings-detail-kind">{model?'模型':'供应商'}</span><h3>{model?model.display_name||model.model_name||modelId:provider.name||providerId}</h3><code>{model?providerId+'/'+modelId:providerId}</code></div><button className="text-button danger-text" onClick={()=>void deleteItem()}>{model?'移除模型':'移除供应商'}</button></div>
          <div className="settings-model-actions">{model&&<button className="text-button" onClick={()=>setSelection({providerId,modelId:null})}><Icon name="globe" size={13}/>编辑供应商</button>}<button className="secondary-button" onClick={()=>setDiscovering(true)}><Icon name="search" size={14}/>发现模型</button><button className="secondary-button" onClick={addModel}><Icon name="plus" size={14}/>手动添加模型</button></div>
          {model?<><p className="settings-item-description">继承自 {provider.name||providerId}。只覆盖需要独立设置的项目。</p><ModelFields key={providerId+'/'+modelId} value={model} provider={provider} onChange={value=>updateProvider({...provider,models:{...provider.models,[modelId!]:value}})}/></>:<><p className="settings-item-description">连接由下级模型默认继承，独立覆盖在各模型中设置。</p><ProviderFields key={providerId} value={provider} onChange={updateProvider}/></>}
        </>:<div className="panel-empty"><Icon name="globe" size={28}/><p>选择一个供应商或模型开始编辑。</p></div>}
      </section>
    </div>
    {discovering&&provider&&<ModelDiscovery key={providerId} providerId={providerId} provider={provider} revision={revision} onClose={()=>setDiscovering(false)} onMerge={(merged,added,updated)=>{updateProvider(merged);setDiscovering(false);notify(`已加入 ${added} 个模型，更新 ${updated} 个能力快照；保存修改后生效。`);}}/>}
  </>;
}
