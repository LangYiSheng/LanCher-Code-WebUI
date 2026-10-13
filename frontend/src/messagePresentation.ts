import type {Message,Trace} from './types.ts';

export function messagePresentation(message:Message){
  const entries=message.trace?.entries||[],streaming=message.status==='streaming';
  if(message.role==='user')return {process:[],answer:message.content,streaming:false,notices:[]};
  const notices=entries.filter(entry=>entry.kind==='notice'&&(entry.metadata?.severity==='error'||message.status!=='complete'&&message.status!=='completed'&&entry.metadata?.severity==='warning'));
  // 只有最后一段正文能成为最终回答；工具之后没有正文时，不把先前的进度说明冒充结果。
  let finalIndex=-1;
  for(let index=entries.length-1;index>=0;index--){
    const entry=entries[index];
    if(entry.kind==='tool_call'||entry.kind==='tool_result')break;
    if(entry.kind==='text'&&entry.text?.trim()){finalIndex=index;break;}
  }
  const hasText=entries.some(entry=>entry.kind==='text'&&entry.text?.trim());
  const fallback=!hasText&&!entries.some(entry=>entry.kind==='tool_call'||entry.kind==='tool_result')
    &&!entries.some(entry=>entry.kind==='notice'&&entry.text===message.content)?message.content:'';
  const answer=streaming?'':finalIndex>=0?entries[finalIndex].text||'':fallback;
  const process=entries.filter((entry,index)=>(streaming||index!==finalIndex)&&!notices.includes(entry));
  if(streaming&&!hasText&&message.content)process.push({kind:'text',text:message.content});
  return {process,answer,streaming,notices};
}

export function thinkingDuration(message:Message,now=Date.now()):string{
  const start=Date.parse(message.timestamp||'');
  const end=message.status==='streaming'?now:Date.parse(message.completed_at||'');
  if(!Number.isFinite(start)||!Number.isFinite(end)||end<start)return '';
  const seconds=Math.floor((end-start)/1000);
  return seconds<60?`${seconds}秒`:`${Math.floor(seconds/60)}分${String(seconds%60).padStart(2,'0')}秒`;
}

// SDK 的增量事件省略完整消息，仍须同步当前轨迹段，避免折叠区显示旧正文。
export function appendMessageText(message:Message,text:string):Message{
  const entries=message.trace?.entries||[],last=entries[entries.length-1];
  const next:Trace={kind:'text',text:entries.length?text:message.content+text,metadata:{state:'streaming'}};
  return {...message,content:message.content+text,trace:{...message.trace,entries:last?.kind==='text'&&last.metadata?.state==='streaming'
    ?[...entries.slice(0,-1),{...last,text:(last.text||'')+text}]:[...entries,next]}};
}
