import type {ChatSummary,Project} from './types';

const sorted=(chats:readonly ChatSummary[])=>[...chats].sort((a,b)=>Number(!!b.pinned)-Number(!!a.pinned)||(b.updated_at||'').localeCompare(a.updated_at||'')||a.id.localeCompare(b.id));
// 导航与搜索只展示已发送首条消息、尚未归档的正式对话。
export function visibleChats(chats:readonly ChatSummary[]):ChatSummary[]{return sorted(chats.filter(chat=>!chat.archived&&!chat.draft));}
export function searchChats(chats:readonly ChatSummary[],projects:readonly Project[],query:string):ChatSummary[]{
  const projectMap=new Map(projects.map(project=>[project.id,project]));
  const words=query.normalize('NFKC').trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);
  return visibleChats(chats).filter(chat=>{
    const project=projectMap.get(chat.project_id);if(!project)return false;
    const text=[chat.title,chat.model_ref,chat.id,chat.sdk_session_id,project.name,project.path].join(' ').normalize('NFKC').toLocaleLowerCase();
    return words.every(word=>text.includes(word));
  });
}
