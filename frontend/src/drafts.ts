import type {ChatSummary} from './types.ts';
export type DraftChats=Record<string,ChatSummary>;
// 仅保存当前草稿的身份与控制选项；输入内容继续使用按聊天隔离的 draft 键。
export function draftSummary(chat:ChatSummary):ChatSummary{
  return {id:chat.id.toLowerCase(),project_id:chat.project_id,title:chat.title||'新聊天',
    draft:true,status:chat.status||'idle',phase:chat.phase||'execute',access:chat.access||'project',
    model_ref:chat.model_ref||'',sdk_session_id:chat.sdk_session_id,updated_at:chat.updated_at,
    pending_config:chat.pending_config,_event_sequence:chat._event_sequence};
}
export function restoreDraftChats(value:unknown):DraftChats{
  if(!value||typeof value!=='object'||Array.isArray(value))return {};
  const result:DraftChats={};
  for(const item of Object.values(value)){
    const chat=item as ChatSummary;
    if(chat&&chat.draft===true&&typeof chat.id==='string'&&/^[a-f0-9]{32}$/i.test(chat.id)
      &&typeof chat.project_id==='string'&&chat.project_id)result[chat.id.toLowerCase()]={...draftSummary(chat),_event_sequence:undefined};
  }
  return result;
}
export function draftCreatePayload(chat:ChatSummary){
  return {project_id:chat.project_id,draft_id:chat.id,title:chat.title,
    ...(chat.model_ref?{model_ref:chat.model_ref}:{}),
    ...(['discuss','plan','execute'].includes(chat.phase)?{phase:chat.phase}:{}),
    ...(['project','full'].includes(chat.access)?{access:chat.access}:{})};
}
