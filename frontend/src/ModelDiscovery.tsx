import {useEffect,useRef,useState} from 'react';
import type {Dict} from './types';
import {ApiError,api} from './api';
import {Modal} from './Dialogs';
import {Icon,Spinner} from './Icon';
import {capabilityList} from './reasoning';
import {discoveryEligible,preserveDiscoverySecrets,type DiscoveryResult} from './discovery';

type Props={providerId:string;provider:Dict;revision:string;projectId?:string;onClose:()=>void;onMerge:(provider:Dict,added:number,updated:number)=>void};
export function ModelDiscovery({providerId,provider,revision,projectId,onClose,onMerge}:Props){
  const [snapshot,setSnapshot]=useState<{identity:string;data:DiscoveryResult}|null>(null),[selected,setSelected]=useState(new Set<string>());
  const [readOnly,setReadOnly]=useState(false);
  const [query,setQuery]=useState(''),[limit,setLimit]=useState(100),[loading,setLoading]=useState(false),[merging,setMerging]=useState(false),[error,setError]=useState('');
  const generation=useRef(0),controller=useRef<AbortController|null>(null);
  const signature=JSON.stringify(provider),identity=JSON.stringify([providerId,revision,projectId,signature]);
  const result=snapshot?.identity===identity?snapshot.data:null;
  const existing=new Set(result?.existing||[]),eligible=result?discoveryEligible(result):[];
  const needle=query.trim().toLocaleLowerCase();
  const rows=(result?.models||[]).filter(model=>!needle||[model.id,model.display_name,model.owned_by].join(' ').toLocaleLowerCase().includes(needle));
  function payload(){return {provider_id:providerId,provider,revision,...(projectId?{project_id:projectId}:{})};}
  async function discover(refresh=false){
    controller.current?.abort();const abort=new AbortController();controller.current=abort;const token=++generation.current;
    setLoading(true);setReadOnly(false);setError('');
    try{const data=await api<DiscoveryResult>('/api/settings/model-discovery',{method:'POST',body:JSON.stringify({...payload(),refresh}),signal:abort.signal});
      if(abort.signal.aborted||token!==generation.current)return;
      setSnapshot({identity,data});const allowed=new Set(discoveryEligible(data));setSelected(current=>new Set([...current].filter(id=>allowed.has(id))));
    }catch(reason){if(!abort.signal.aborted&&token===generation.current){if(reason instanceof ApiError&&[401,403].includes(reason.status)){setSnapshot(null);setSelected(new Set());}else setReadOnly(true);setError((reason instanceof Error?reason.message:String(reason))+(result?' 请重新发现后再加入模型。':''));}}
    finally{if(token===generation.current&&!abort.signal.aborted)setLoading(false);}
  }
  useEffect(()=>{setSnapshot(null);setSelected(new Set());setMerging(false);setLoading(true);setReadOnly(false);setError('');void discover();return()=>{generation.current++;controller.current?.abort();};},[providerId,signature,revision,projectId]);
  useEffect(()=>setLimit(100),[query]);
  async function merge(){
    if(!result||loading||merging||readOnly)return;const token=++generation.current;const abort=new AbortController();controller.current?.abort();controller.current=abort;
    setMerging(true);setError('');
    try{const data=await api<{provider:Dict;added:number;updated:number}>('/api/settings/model-discovery/merge',{method:'POST',body:JSON.stringify({...payload(),discovery_id:result.discovery_id,selected_ids:[...selected]}),signal:abort.signal});
      if(abort.signal.aborted||token!==generation.current)return;
      onMerge(preserveDiscoverySecrets(provider,data.provider),data.added,data.updated);
    }catch(reason){if(!abort.signal.aborted&&token===generation.current)setError(reason instanceof Error?reason.message:String(reason));}
    finally{if(token===generation.current&&!abort.signal.aborted)setMerging(false);}
  }
  return <Modal title={'发现模型 · '+(provider.name||providerId)} subtitle="查询端点模型列表，加入设置草稿后统一保存。" onClose={onClose} className="model-discovery-modal">
    <div className="discovery-summary"><span>{result?`${result.models.length} 个模型 · ${existing.size} 已加入 · ${selected.size} 已选`:'读取当前连接的模型列表'}</span><span className="tag">{loading?'查询中':readOnly?'上次结果 · 只读':result?.stale?'上次结果':result?.cached?'缓存':'在线'}</span><button className="text-button" disabled={loading||merging} onClick={()=>void discover(true)}><Icon name="refresh" size={13}/>刷新</button></div>
    {result?.fetched_at&&<p className="small-note discovery-fetched">获取时间：{new Date(result.fetched_at).toLocaleString('zh-CN')}</p>}
    {result?.notice&&<p className={'discovery-notice '+(result.stale?'stale':'')}>{result.notice}</p>}
    <div className="discovery-search"><Icon name="search" size={16}/><input autoFocus aria-label="搜索发现的模型" placeholder="搜索模型名称、API ID 或归属…" value={query} onChange={event=>setQuery(event.target.value)}/></div>
    <div className="discovery-selection"><button className="text-button" disabled={loading||merging||readOnly||!eligible.length} onClick={()=>setSelected(new Set(eligible))}>全选可加入模型</button><button className="text-button" disabled={merging||readOnly||!selected.size} onClick={()=>setSelected(new Set())}>清空选择</button><span>{needle?rows.length+' 个匹配 · 筛选保留已选项':''}</span></div>
    {error&&<p className="inline-error" role="alert">{error}</p>}
    <div className="discovery-models" aria-busy={loading}>
      {loading&&!result?<div className="panel-empty"><Spinner/>正在查询模型列表…</div>:rows.slice(0,limit).map(model=>{
        const added=existing.has(model.id),cap=model.capabilities||{};
        return <label className={'discovery-model '+(added?'already-added':'')} key={model.id}>
          <input type="checkbox" aria-label={'选择模型 '+model.id} disabled={added||loading||merging||readOnly} checked={selected.has(model.id)} onChange={event=>setSelected(current=>{const next=new Set(current);event.target.checked?next.add(model.id):next.delete(model.id);return next;})}/>
          <div><strong>{model.display_name||model.id}{added&&<small>已加入</small>}</strong><code>{model.id}</code><span>{model.owned_by||'归属未声明'} · 窗口 {model.context_window?.toLocaleString('zh-CN')||'未声明'} · 总输出 {model.max_output_tokens?.toLocaleString('zh-CN')||'未声明'}</span><span>推理档位：{capabilityList(cap.effort_levels,'不提供手动档位')}</span></div>
        </label>;
      })}
      {!loading&&!rows.length&&<p className="panel-empty">{result?needle?'没有匹配的模型。':'端点未返回可用模型，可以继续手动添加。':'查询失败后可重试，或关闭后手动添加。'}</p>}
      {rows.length>limit&&<button className="secondary-button discovery-more" onClick={()=>setLimit(current=>current+100)}>加载更多（剩余 {rows.length-limit} 个）</button>}
    </div>
    <div className="modal-footer"><button className="secondary-button" onClick={onClose}>取消</button><button className="primary-button" disabled={!result||loading||merging||readOnly||(!selected.size&&!existing.size)} onClick={()=>void merge()}>{merging?<Spinner/>:<Icon name="plus" size={15}/>} {selected.size?'加入所选（'+selected.size+'）':'更新已有模型信息'}</button></div>
  </Modal>;
}
