import type {AgentEvent,Bootstrap,ChatDetail,ChatSummary,Message,WorkbenchState} from './types.ts';
import {appendMessageText} from './messagePresentation.ts';
export const initialState:WorkbenchState={boot:null,projects:[],chats:[],details:{},sequence:0};
function upsert<T extends {id:string}>(items:T[],item:T):T[]{const found=items.find(x=>x.id===item.id);return found?items.map(x=>x.id===item.id?{...x,...item}:x):[item,...items];}
export function mergeMessages(older:Message[],newer:Message[]):Message[]{const result=new Map<string,Message>();for(const message of [...older,...newer])if(message.role!=='system')result.set(message.id,message);return [...result.values()];}
export function receiveBootstrap(state:WorkbenchState,boot:Bootstrap):WorkbenchState{return {...state,boot,projects:boot.projects,chats:boot.chats.map(chat=>{const current=state.chats.find(x=>x.id===chat.id);return current&&(current._event_sequence||0)>(boot.watermark||0)?current:chat;}),sequence:Math.max(state.sequence,boot.watermark||0)};}
export function receiveDetail(state:WorkbenchState,detail:ChatDetail,older=false):WorkbenchState {
  const current=state.details[detail.id];
  let next=detail;
  if(current){
    const streamingIsNewer=(current.watermark||0)>(detail.watermark||0);
    next=streamingIsNewer?{...detail,...current,messages:mergeMessages(detail.messages,current.messages)}:{...current,...detail,messages:older?mergeMessages(detail.messages,current.messages):mergeMessages(current.messages,detail.messages)};
    if(older){next.has_more=detail.has_more;next.next_before=detail.next_before;}
  }
  return {...state,chats:upsert(state.chats,next),details:{...state.details,[detail.id]:next}};
}
// 全局事件游标只用于去重，消息和运行状态严格归属各自的聊天。
export function applyEvent(state:WorkbenchState,event:AgentEvent):WorkbenchState {
  if(event.sequence && event.sequence<=state.sequence)return state;
  let next={...state,sequence:Math.max(state.sequence,event.sequence||0)};
  if(event.kind==='chat_state'&&event.chat){next.chats=upsert(state.chats,{...event.chat,_event_sequence:event.sequence});if(state.details[event.chat.id])next.details={...state.details,[event.chat.id]:{...state.details[event.chat.id],...event.chat,watermark:event.sequence}};}
  if(event.kind==='project_state'&&event.project)next.projects=upsert(state.projects,event.project);
  if(event.kind==='project_removed'){next.projects=next.projects.filter(x=>x.id!==event.project_id);const ids=new Set(next.chats.filter(x=>x.project_id===event.project_id).map(x=>x.id));next.chats=next.chats.filter(x=>!ids.has(x.id));next.details=Object.fromEntries(Object.entries(next.details).filter(([id])=>!ids.has(id)));return next;}
  if(event.kind==='chat_removed'){next.chats=next.chats.filter(x=>x.id!==event.chat_id);next.details={...next.details};if(event.chat_id)delete next.details[event.chat_id];return next;}
  const id=event.chat_id;
  if(!id||!state.details[id])return next;
  let detail={...(next.details[id]||state.details[id]),watermark:event.sequence};
  if(event.message)detail.messages=mergeMessages(detail.messages,[event.message]);
  else if(event.kind==='assistant_text_delta'&&event.text){const last=[...detail.messages].reverse().find(x=>x.role==='assistant');if(last?.status==='streaming')detail.messages=detail.messages.map(x=>x.id===last.id?appendMessageText(x,event.text):x);}
  if(event.kind==='permission_request_created'&&event.permission_request)detail.permissions=[...detail.permissions.filter(x=>x.request_id!==event.permission_request.request_id),event.permission_request];
  if(['permission_request_resolved','permission_request_closed'].includes(event.kind)){const req=event.permission_resolution?.request_id||event.permission_request?.request_id;detail.permissions=detail.permissions.filter(x=>x.request_id!==req);}
  if(event.kind==='pending_input_changed'&&event.queue)detail.queue=event.queue;
  if(event.kind==='processes_updated'&&event.processes)detail.processes=event.processes;
  if(event.kind==='usage_updated'&&event.usage)detail.usage={...detail.usage,answer:event.usage};
  if(event.kind==='phase_changed'&&event.work_phase)detail.phase=event.work_phase;
  if(event.kind==='access_changed'&&event.execution_access)detail.access=event.execution_access;
  if(event.kind==='compaction_updated')detail.context={...detail.context,compaction:event.compaction};
  // SDK 单轮完成可能推进后续输入，只有 chat_state 更新宿主任务的终态。
  next.details={...next.details,[id]:detail};
  return next;
}
export function updateChat(state:WorkbenchState,chat:ChatSummary):WorkbenchState{return {...state,chats:upsert(state.chats,chat),details:state.details[chat.id]?{...state.details,[chat.id]:{...state.details[chat.id],...chat}}:state.details};}
