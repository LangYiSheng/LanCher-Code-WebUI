import {useEffect,useState} from 'react';
import type {ChatSummary,Project} from './types';
import {Select} from './Select';
import {Icon,Spinner} from './Icon';
import {useDialogs} from './Dialogs';
import {Field} from './SettingsFields';

type Props={chats:ChatSummary[];projects:Project[];onOpenArchived:(id:string)=>void;onRestoreArchived:(id:string)=>Promise<void>;notify:(message:string)=>void};
export function SettingsStorage({chats,projects,onOpenArchived,onRestoreArchived,notify}:Props){
  const {confirm}=useDialogs();const [query,setQuery]=useState(''),[projectId,setProjectId]=useState('');
  const [pending,setPending]=useState<Record<string,boolean>>({}),[errors,setErrors]=useState<Record<string,string>>({});
  const archived=chats.filter(chat=>chat.archived&&!chat.draft),needle=query.trim().toLowerCase();
  const visible=archived.filter(chat=>{const project=projects.find(item=>item.id===chat.project_id);return (!projectId||chat.project_id===projectId)&&(!needle||[chat.title,chat.id,chat.sdk_session_id,chat.model_ref,project?.name,project?.path].join(' ').toLowerCase().includes(needle));}).sort((a,b)=>(b.updated_at||'').localeCompare(a.updated_at||''));
  useEffect(()=>{if(projectId&&!projects.some(project=>project.id===projectId))setProjectId('');},[projects,projectId]);
  async function restore(id:string){if(pending[id])return;setPending(values=>({...values,[id]:true}));setErrors(values=>({...values,[id]:''}));try{await onRestoreArchived(id);notify('对话已恢复到项目列表。');}catch(reason){setErrors(values=>({...values,[id]:reason instanceof Error?reason.message:String(reason)}));}finally{setPending(values=>({...values,[id]:false}));}}
  return <>
    <section className="settings-storage-section"><div className="settings-subheading"><div><h3>归档对话</h3></div><span className="settings-count">{archived.length}</span></div>
      <div className="archive-filters"><div className="settings-directory-search"><Icon name="search" size={14}/><input aria-label="搜索归档对话" placeholder="搜索标题、模型、ID 或项目…" value={query} onChange={event=>setQuery(event.target.value)}/></div><Select aria-label="按项目筛选归档对话" value={projectId} onChange={event=>setProjectId(event.target.value)}><option value="">所有项目</option>{projects.map(project=><option key={project.id} value={project.id}>{project.name}</option>)}</Select></div>
      <div className="settings-archive-list">{visible.map(chat=>{const project=projects.find(item=>item.id===chat.project_id);const date=chat.updated_at?new Date(chat.updated_at):null;return <article className="settings-archive-row" key={chat.id}><div><h4>{chat.title||'未命名对话'}</h4><p><span>{project?.name||'项目不可用'}</span><span>{date&&!Number.isNaN(date.getTime())?date.toLocaleString('zh-CN'):'时间未知'}</span></p><code title={chat.model_ref}>{chat.model_ref||'模型未记录'}</code>{errors[chat.id]&&<p className="inline-error" role="alert">{errors[chat.id]}</p>}</div><div className="archive-row-actions"><button className="secondary-button" disabled={pending[chat.id]} onClick={()=>onOpenArchived(chat.id)}><Icon name="history" size={14}/>查看记录</button><button className="secondary-button" title="恢复后回到项目列表" disabled={pending[chat.id]} onClick={()=>void restore(chat.id)}>{pending[chat.id]?<Spinner/>:<Icon name="back" size={14}/>}恢复</button></div></article>;})}{!visible.length&&<div className="panel-empty">{archived.length?'没有符合筛选条件的归档对话。':'还没有归档对话。'}</div>}</div>
    </section>
    <section className="settings-storage-section"><div className="settings-subheading"><div><h3>浏览器输入草稿</h3></div></div><Field label="清理本地输入草稿"><button className="secondary-button" onClick={async()=>{if(!await confirm({title:'清理本地输入草稿',message:'将清除这个浏览器保存的所有未发送输入草稿。正式对话记录会保留。',confirmLabel:'清理草稿'}))return;try{for(const key of Object.keys(localStorage))if(key.startsWith('lancher-webui:draft:'))localStorage.removeItem(key);notify('已清理本地输入草稿。');}catch(reason){notify(String(reason));}}}>清理草稿</button></Field></section>
  </>;
}
