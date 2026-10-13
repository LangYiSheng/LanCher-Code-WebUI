import {useEffect,useId,useLayoutEffect,useRef,useState,type CSSProperties} from 'react';
import {createPortal} from 'react-dom';
import type {ChatSummary,ModelChoice} from './types';
import type {ActionFn} from './ChatView';
import {Icon,Spinner} from './Icon';
import {EFFORT_LABELS,effortOptions} from './reasoning';

export function ModelEffortPicker({summary,models,disabled,action,notify}:{summary?:ChatSummary;models:ModelChoice[];disabled:boolean;action:ActionFn;notify:(text:string)=>void}){
  const [open,setOpen]=useState(false),[query,setQuery]=useState(''),[pending,setPending]=useState(false);
  const [preview,setPreview]=useState<string|null>(null),[position,setPosition]=useState<CSSProperties>({});
  const trigger=useRef<HTMLButtonElement>(null),popover=useRef<HTMLDivElement>(null),search=useRef<HTMLInputElement>(null);
  const lock=useRef(false),id=useId(),levels=effortOptions(summary);
  const current=summary?.reasoning_effort||'auto',effort=preview&&levels.includes(preview)?preview:current;
  const index=Math.max(0,levels.indexOf(effort)),model=models.find(item=>item.id===summary?.model_ref);
  const groups=new Map<string,ModelChoice[]>();
  for(const item of models){const provider=item.provider||'其他供应商';if((provider+' '+item.name+' '+item.id).toLowerCase().includes(query.trim().toLowerCase()))groups.set(provider,[...(groups.get(provider)||[]),item]);}
  function dismiss(focus=false){setOpen(false);setPreview(null);if(focus)trigger.current?.focus();}
  useEffect(()=>{if(disabled)dismiss();},[disabled]);
  useEffect(()=>{setPreview(null);},[summary?.model_ref,current]);
  useLayoutEffect(()=>{
    if(!open)return;
    const place=()=>{const rect=trigger.current?.getBoundingClientRect();if(!rect)return;const width=Math.min(344,window.innerWidth-24);setPosition({width,left:Math.max(12,Math.min(rect.right-width,window.innerWidth-width-12)),bottom:window.innerHeight-rect.top+10,maxHeight:Math.max(100,rect.top-22)});};
    place();search.current?.focus();window.addEventListener('resize',place);
    const outside=(event:PointerEvent)=>{if(!popover.current?.contains(event.target as Node)&&!trigger.current?.contains(event.target as Node))dismiss();};
    document.addEventListener('pointerdown',outside);
    return()=>{window.removeEventListener('resize',place);document.removeEventListener('pointerdown',outside);};
  },[open]);
  async function commit(kind:'model'|'effort',value:string){
    if(lock.current||disabled)return;
    if(kind==='effort'&&value===current){setPreview(null);return;}
    const focused=popover.current?.contains(document.activeElement)?document.activeElement as HTMLElement:null;
    lock.current=true;setPending(true);
    try{await action(kind,kind==='model'?{model_ref:value}:{effort:value});}
    catch(error){notify(error instanceof Error?error.message:String(error));}
    finally{lock.current=false;setPending(false);setPreview(null);requestAnimationFrame(()=>{if(focused&&popover.current?.contains(focused)&&document.activeElement===document.body)focused.focus();});}
  }
  return <>
    <button ref={trigger} className="model-effort-trigger" aria-label="选择模型与思考等级" aria-haspopup="dialog" aria-expanded={open} aria-controls={open?id:undefined} disabled={disabled} title={model?.name||summary?.model_ref||'选择模型'} onClick={()=>{setQuery('');setOpen(value=>!value);}}>
      <span className="model-trigger-name">{model?.name||summary?.model_ref||'选择模型'}</span><span className="model-trigger-separator">·</span><span className="model-trigger-effort">{EFFORT_LABELS[current]||current}</span><Icon name="down" size={12}/>
    </button>
    {open&&createPortal(<div ref={popover} id={id} role="dialog" aria-label="模型与思考等级" className="model-effort-popover" style={position}
      onBlur={event=>{if(event.relatedTarget&&!event.currentTarget.contains(event.relatedTarget as Node)&&event.relatedTarget!==trigger.current)dismiss();}}
      onKeyDown={event=>{if(event.key==='Escape'){event.preventDefault();event.stopPropagation();dismiss(true);}}}>
      <header><strong>选择模型</strong>{pending?<Spinner/>:<span>{models.length} 个模型</span>}<button className="icon-button" aria-label="关闭模型选择" onClick={()=>dismiss(true)}><Icon name="close" size={14}/></button></header>
      <label className="model-search"><Icon name="search" size={14}/><input ref={search} aria-label="搜索模型或供应商" placeholder="搜索模型或供应商" value={query} onChange={event=>setQuery(event.target.value)}/></label>
      <div className="model-groups" role="group" aria-label="可用模型">
        {[...groups].map(([provider,items])=><section key={provider} className="model-provider"><h3>{provider}</h3>{items.map(item=><button key={item.id} className={'model-option '+(item.id===summary?.model_ref?'selected':'')} aria-pressed={item.id===summary?.model_ref} disabled={pending} onClick={()=>void commit('model',item.id)}><span>{item.name}</span>{item.id===summary?.model_ref&&<Icon name="check" size={15}/>}</button>)}</section>)}
        {!groups.size&&<p className="model-no-results">没有匹配的模型</p>}
      </div>
      <div className="effort-control"><div className="effort-heading"><span><Icon name="spark" size={14}/>思考等级</span><strong>{EFFORT_LABELS[effort]||effort}</strong></div>
        {levels.length>1?<><input className="effort-slider" type="range" min={0} max={levels.length-1} step={1} value={index} aria-label="思考等级" aria-valuetext={EFFORT_LABELS[effort]||effort} disabled={pending}
          style={{'--range-progress':`${index/(levels.length-1)*100}%`} as CSSProperties}
          onChange={event=>setPreview(levels[Number(event.target.value)])}
          onPointerUp={event=>void commit('effort',levels[Number(event.currentTarget.value)])}
          onPointerCancel={()=>setPreview(null)}
          onKeyUp={event=>{if(['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','Home','End','PageUp','PageDown'].includes(event.key))void commit('effort',levels[Number(event.currentTarget.value)]);}}
          onBlur={event=>{if(preview!==null)void commit('effort',levels[Number(event.currentTarget.value)]);}}/>
          <div className="effort-stops">{levels.map(level=><button key={level} disabled={pending} aria-label={'思考等级：'+(EFFORT_LABELS[level]||level)} aria-pressed={level===effort} onClick={()=>void commit('effort',level)}>{EFFORT_LABELS[level]||level}</button>)}</div></>
          :<p className="effort-note">{summary?.effort_known?'仅支持自动':'等级待确认'}</p>}

      </div>
    </div>,document.body)}
  </>;
}
