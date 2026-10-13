import {useEffect,useRef,useState} from 'react';
import type {ChatDetail,Dict} from './types';
import type {ActionFn} from './ChatView';
import {Icon,Spinner} from './Icon';
import {appendProcessOutput,emptyProcessPage,groupProcesses,processState,type ProcessPage} from './processPresentation';

const processViews=new Map<string,Record<string,ProcessPage>>();
export function ProcessesPanel({chat,action,notify,enabled=true}:{chat:ChatDetail;action:ActionFn;notify:(text:string)=>void;enabled?:boolean}){
  const [chosen,setChosen]=useState(''),[history,setHistory]=useState(false),[follow,setFollow]=useState(false);
  const [pages,setPages]=useState<Record<string,ProcessPage>>(()=>processViews.get(chat.id)||{});
  const [reading,setReading]=useState(''),[pending,setPending]=useState(''),[error,setError]=useState('');
  const pagesRef=useRef(pages),actionRef=useRef(action),requests=useRef(new Set<string>()),reread=useRef(new Set<string>()),mounted=useRef(true),mutation=useRef(false);
  const output=useRef<HTMLPreElement>(null),shouldFollow=useRef(true);
  pagesRef.current=pages;actionRef.current=action;
  const groups=groupProcesses(chat.processes);
  const process=chat.processes.find(item=>item.process_id===chosen)||groups.active[0]||groups.finished[0];
  const selected=process?.process_id||'',state=processState(process||{}),page=pages[selected]||emptyProcessPage();
  const selectedRef=useRef(selected);selectedRef.current=selected;
  useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;};},[]);
  function updatePage(id:string,update:(old:ProcessPage)=>ProcessPage){
    const next={...pagesRef.current,[id]:update(pagesRef.current[id]||emptyProcessPage())};
    pagesRef.current=next;setPages(next);processViews.set(chat.id,next);
    if(processViews.size>20)processViews.delete(processViews.keys().next().value!);
  }
  async function read(id:string){
    if(!id||!enabled)return;
    if(requests.current.has(id)){reread.current.add(id);return;}
    requests.current.add(id);setReading(id);setError('');
    try{const result=await actionRef.current('process_read',{process_id:id,cursor:pagesRef.current[id]?.cursor||0,max_chars:16000});
      if(!mounted.current)return;
      if(result)updatePage(id,current=>appendProcessOutput(current,result));
      else if(selectedRef.current===id){setError('日志读取失败，请稍后重试。');setFollow(false);}
    }catch(err){if(mounted.current&&selectedRef.current===id){setError(err instanceof Error?err.message:String(err));setFollow(false);}}
    finally{requests.current.delete(id);if(mounted.current){setReading(current=>current===id?'':current);if(reread.current.delete(id)&&selectedRef.current===id)void readRef.current(id);}}
  }
  const readRef=useRef(read);readRef.current=read;
  useEffect(()=>{shouldFollow.current=true;setError('');if(enabled&&selected)void readRef.current(selected);},[selected,enabled,process?.status]);
  // 只在用户开启跟随后刷新；收起面板、切换标签、进程退出时清除计时器。
  useEffect(()=>{if(!enabled||!follow||!state.active||!selected)return;const timer=setInterval(()=>void readRef.current(selected),2000);return()=>clearInterval(timer);},[enabled,follow,state.active,selected]);
  useEffect(()=>{if(shouldFollow.current&&output.current)output.current.scrollTop=output.current.scrollHeight;},[page.output,selected]);
  async function perform(kind:string){
    if(!selected||mutation.current)return;const id=selected,sent=page.input;
    mutation.current=true;setPending(kind);setError('');
    try{const result=await actionRef.current(kind,{process_id:id,...(kind==='process_write'?{text:sent+'\n'}:{})});
      if(result&&mounted.current&&kind==='process_write'){updatePage(id,current=>({...current,input:current.input===sent?'':current.input}));notify('输入已发送到进程。');}
    }catch(err){if(mounted.current)setError(err instanceof Error?err.message:String(err));}
    finally{mutation.current=false;if(mounted.current)setPending('');}
  }
  function row(item:Dict){const status=processState(item);return <button key={item.process_id} className={'process-row '+(item.process_id===selected?'selected':'')} aria-pressed={item.process_id===selected} onClick={()=>{setChosen(item.process_id);setFollow(false);}}>
    <span className={'process-indicator '+status.tone}/><span className="process-row-main"><strong>{item.description||item.command||item.process_id}</strong><small>PID {item.pid??'—'} · {item.lifetime==='session'?'会话保留':'本轮任务'}{item.exit_code!=null?' · 退出码 '+item.exit_code:''}</small></span><span className={'process-status '+status.tone}>{status.label}</span>
  </button>;}
  return <div className="process-panel"><header className="panel-heading"><div><h2>托管进程</h2></div><span className={'panel-count '+(groups.active.length?'success':'')}>{groups.active.length} 个活动</span></header>
    <section className="process-list" aria-label="活动进程">
      {groups.active.length?groups.active.map(row):<div className="compact-empty"><Icon name="check" size={16}/><span>暂无运行中的进程</span></div>}
    </section>
    {groups.finished.length>0&&<section className="process-history"><button className="process-history-toggle" aria-expanded={history||!groups.active.length} onClick={()=>setHistory(value=>!value)} disabled={!groups.active.length}><Icon name="chevron" size={12} style={{transform:history||!groups.active.length?'rotate(90deg)':undefined}}/>已结束 <span>{groups.finished.length}</span></button>{(history||!groups.active.length)&&<div className="process-history-list">{groups.finished.map(row)}</div>}</section>}
    {process?<section className="process-detail" aria-label="进程详情"><div className="section-heading"><h3>{process.description||'进程详情'}</h3><span className={'process-status '+state.tone}>{state.label}</span></div>
      <pre className="process-command">{process.command||process.process_id}</pre>
      <dl className="process-facts"><div><dt>PID</dt><dd>{process.pid??'—'}</dd></div><div><dt>保留范围</dt><dd>{process.lifetime==='session'?'整个会话':'本轮任务'}</dd></div>{process.exit_code!=null&&<div><dt>退出码</dt><dd>{process.exit_code}</dd></div>}{process.cwd&&<div className="process-cwd"><dt>目录</dt><dd title={process.cwd}>{process.cwd}</dd></div>}</dl>
      {process.exit_reason&&<p className="small-note">结束原因：{process.exit_reason}</p>}
      {(state.canStop||state.canBackground)&&<div className="row-actions process-actions">{state.canBackground&&<button disabled={!!pending} onClick={()=>void perform('process_background')}><Icon name="process_background" size={13}/>保留到会话</button>}{state.canStop&&<button className="danger-text" disabled={!!pending} onClick={()=>void perform('process_stop')}>{pending==='process_stop'?<Spinner/>:<Icon name="stop" size={12}/>}停止进程</button>}</div>}
      <div className="process-output-heading"><h3>输出日志</h3>{state.active&&<label><input type="checkbox" checked={follow} onChange={event=>setFollow(event.target.checked)}/>自动跟随</label>}<button className="text-button" disabled={reading===selected} onClick={()=>void read(selected)}>{reading===selected?<Spinner/>:<Icon name="refresh" size={13}/>}刷新</button></div>
      {error&&<p className="inline-error" role="alert">{error}</p>}
      <pre ref={output} tabIndex={0} aria-label="进程输出日志" className="process-output" onScroll={event=>{const el=event.currentTarget;shouldFollow.current=el.scrollHeight-el.scrollTop-el.clientHeight<30;}}>{page.output||(reading===selected?'正在读取日志…':page.loaded?'暂无输出':'尚未读取日志')}</pre>
      {page.trimmed&&<p className="small-note">仅展示最近 200,000 个字符。</p>}{page.more&&<button className="text-button" disabled={reading===selected} onClick={()=>void read(selected)}>继续读取后续输出<Icon name="down" size={12}/></button>}
      {state.canWrite&&<form className="process-input" onSubmit={event=>{event.preventDefault();if(page.input&&!pending)void perform('process_write');}}><input aria-label="进程输入" placeholder="输入内容…" value={page.input} onChange={event=>updatePage(selected,current=>({...current,input:event.target.value}))}/><button className="secondary-button" disabled={!page.input||!!pending}>发送</button></form>}
    </section>:null}
  </div>;
}
