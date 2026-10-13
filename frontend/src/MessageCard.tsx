import {memo,useEffect,useId,useState,useRef} from 'react';
import type {Message,Trace} from './types';
import {pretty} from './api';
import {Icon,Spinner,toolIconName} from './Icon';
import {Markdown} from './Markdown';
import {messagePresentation,thinkingDuration} from './messagePresentation';

const ToolCard=memo(function ToolCard({entry,result,onFile}:{entry:Trace;result?:Trace;onFile:(path:string)=>void}){
  const target=entry.arguments?.path||entry.arguments?.file_path;const error=result?.ok===false;const [open,setOpen]=useState(error);const manual=useRef(false);useEffect(()=>{if(error&&!manual.current)setOpen(true);},[error]);
  return <details className={`tool-card ${error?'error':''}`} open={open} onToggle={e=>{if(e.currentTarget.open!==open){manual.current=true;setOpen(e.currentTarget.open);}}}><summary><Icon name={toolIconName(entry.tool_name)} size={15}/><strong>{entry.tool_name}</strong><span className="tool-target">{target||entry.arguments?.command||entry.arguments?.query||entry.arguments?.pattern||''}</span><span className={`tool-result-tag ${error?'error':''}`}>{result?(error?'失败':'完成'):'执行中'}</span><Icon name="down" size={12}/></summary><div className="tool-body"><label>参数</label><pre>{pretty(entry.arguments)}</pre>{target&&<button className="text-button" onClick={()=>onFile(target)}><Icon name="file" size={14}/>查看文件</button>}</div></details>;
});
// 结果保留在原始轨迹位置，不能挪回调用卡而改变并行批次顺序。
const ToolResultCard=memo(function ToolResultCard({entry,call,onFile}:{entry:Trace;call?:Trace;onFile:(path:string)=>void}){
  const target=call?.arguments?.path||call?.arguments?.file_path;const error=entry.ok===false;const [open,setOpen]=useState(error);const manual=useRef(false);useEffect(()=>{if(error&&!manual.current)setOpen(true);},[error]);
  return <details className={`tool-card tool-result-card ${error?'error':''}`} open={open} onToggle={e=>{if(e.currentTarget.open!==open){manual.current=true;setOpen(e.currentTarget.open);}}}><summary><Icon name={toolIconName(entry.tool_name||call?.tool_name)} size={15}/><strong>{entry.tool_name||call?.tool_name||'工具'} · 结果</strong><span className="tool-target">{target||call?.arguments?.command||call?.arguments?.query||call?.arguments?.pattern||''}</span><span className={`tool-result-tag ${error?'error':''}`}>{error?'失败':'完成'}</span><Icon name="down" size={12}/></summary><div className="tool-body"><pre>{entry.text||pretty(entry.metadata)}</pre>{target&&<button className="text-button" onClick={()=>onFile(target)}><Icon name="file" size={14}/>查看文件</button>}</div></details>;
});
function TraceContent({entries,showThinking,onFile}:{entries:Trace[];showThinking:boolean;onFile:(path:string)=>void}){
  const results=new Map(entries.filter(entry=>entry.kind==='tool_result').map(entry=>[entry.call_id,entry]));
  const calls=new Map(entries.filter(entry=>entry.kind==='tool_call').map(entry=>[entry.call_id,entry]));
  return entries.map((entry,index)=>{
    if(entry.kind==='tool_call')return <ToolCard key={'call:'+(entry.call_id||index)} entry={entry} result={results.get(entry.call_id)} onFile={onFile}/>;
    if(entry.kind==='tool_result')return <ToolResultCard key={'result:'+(entry.call_id||index)} entry={entry} call={calls.get(entry.call_id)} onFile={onFile}/>;
    if(entry.kind==='text')return <Markdown key={index} text={entry.text||''}/>;
    if(entry.kind==='thinking')return showThinking?<pre className="thinking-fragment" key={index}>{entry.text}</pre>:null;
    const text=entry.text||entry.metadata?.summary;
    return text?<div className={'trace-note '+entry.kind} key={index}><Icon name={entry.kind==='compaction'?'archive':'info'} size={13}/><span>{text}</span></div>:null;
  });
}

function ThinkingLabel({message}:{message:Message}){
  const [clock,setClock]=useState(Date.now),streaming=message.status==='streaming';
  useEffect(()=>{
    if(!streaming)return;
    const timer=setInterval(()=>setClock(Date.now()),1000);
    return()=>clearInterval(timer);
  },[streaming]);
  const duration=thinkingDuration(message,clock);
  return <span>{streaming?'思考':'已思考'}{duration?' '+duration:''}</span>;
}

function ThinkingProcess({entries,message,showThinking,onFile}:{entries:Trace[];message:Message;showThinking:boolean;onFile:(path:string)=>void}){
  const streaming=message.status==='streaming';
  const id=useId(),[open,setOpen]=useState(streaming);
  return <section className={'thinking-process '+(streaming?'is-thinking':'')}>
    <button type="button" className="thinking-toggle" aria-expanded={open} aria-controls={id} onClick={()=>setOpen(value=>!value)}>
      {streaming&&<Spinner/>}<ThinkingLabel message={message}/><Icon name="chevron" className={open?'expanded':''} size={12}/>
    </button>
    <div id={id} hidden={!open}>{open&&<div className="thinking-content"><TraceContent entries={entries} showThinking={showThinking} onFile={onFile}/></div>}</div>
  </section>;
}

export const MessageCard=memo(function MessageCard({message:source,active,showThinking,timestamps,onFile,notify}:{message:Message;active:boolean;showThinking:boolean;timestamps:boolean;onFile:(path:string)=>void;notify:(text:string)=>void}){
  const message=source.status==='streaming'&&!active?{...source,status:'interrupted'}:source;
  const view=messagePresentation(message);
  const [copied,setCopied]=useState(false),user=message.role==='user';
  const hasProcess=view.streaming||view.process.some(entry=>entry.kind!=='thinking'||showThinking);
  useEffect(()=>{if(!copied)return;const timer=setTimeout(()=>setCopied(false),1800);return()=>clearTimeout(timer);},[copied]);
  async function copy(){
    try{await navigator.clipboard.writeText(view.answer);setCopied(true);}
    catch{notify('复制失败，请重试。');}
  }
  return <article className={'message '+message.role}>
    <div className="message-meta">{!user&&<Icon name="spark" size={14} className="message-author-mark"/>}<strong>{user?'你':'LanCher'}</strong>
      {timestamps&&message.timestamp&&<time>{new Date(message.timestamp).toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit'})}</time>}
      {['cancelled','error','interrupted'].includes(message.status)&&<span className="message-state">{message.status==='cancelled'?'已停止':message.status==='interrupted'?'已中断':'出错'}</span>}
      {!!view.answer&&<button className="icon-button copy-message" aria-label={user?'复制消息':'复制最终回答'} title={copied?'已复制':user?'复制消息':'复制最终回答'} onClick={()=>void copy()}><Icon name={copied?'check':'copy'} size={14}/></button>}
    </div>
    <div className="message-content">
      {hasProcess&&<ThinkingProcess key={message.status} entries={view.process} message={message} showThinking={showThinking} onFile={onFile}/>}
      {view.notices.map((entry,index)=><div className="trace-note message-error" role="alert" key={index}><Icon name="info" size={13}/><span>{entry.text}</span></div>)}
      {!!view.answer&&<div className={user?'user-text':'final-answer'}><Markdown text={view.answer}/></div>}
    </div>
  </article>;
});
