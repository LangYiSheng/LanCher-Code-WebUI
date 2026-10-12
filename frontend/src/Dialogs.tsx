import {createContext,useCallback,useContext,useEffect,useId,useMemo,useRef,useState,type ReactNode} from 'react';
import {Icon,Spinner} from './Icon';

export function Modal({title,subtitle,onClose,children,className='',dismissible=true}:{title:string;subtitle?:string;onClose:()=>void;children:ReactNode;className?:string;dismissible?:boolean}){
  const ref=useRef<HTMLDialogElement>(null);const titleId=useId();
  useEffect(()=>{const dialog=ref.current;if(dialog&&!dialog.open)dialog.showModal();return()=>dialog?.close();},[]);
  return <dialog ref={ref} className={'modal surface-panel '+className} aria-labelledby={titleId}
    onCancel={event=>{event.preventDefault();if(dismissible)onClose();}}
    onClick={event=>{if(dismissible&&event.target===ref.current){const rect=ref.current.getBoundingClientRect();if(event.clientX<rect.left||event.clientX>rect.right||event.clientY<rect.top||event.clientY>rect.bottom)onClose();}}}>
    <div className="modal-heading"><div><h2 id={titleId}>{title}</h2>{subtitle&&<p>{subtitle}</p>}</div><button type="button" className="icon-button" aria-label="关闭弹窗" disabled={!dismissible} onClick={onClose}><Icon name="close"/></button></div>{children}
  </dialog>;
}

type Common={title:string;confirmLabel?:string;danger?:boolean};
type PromptOptions=Common&{label:string;initialValue?:string;subtitle?:string;maxLength?:number;multiline?:boolean;validate?:(value:string)=>string|undefined;onSubmit?:(value:string)=>void|Promise<void>};
type ConfirmOptions=Common&{message:string};
type Request={kind:'prompt';options:PromptOptions;resolve:(value:string|null)=>void}|{kind:'confirm';options:ConfirmOptions;resolve:(value:boolean)=>void};
type DialogApi={prompt:(options:PromptOptions)=>Promise<string|null>;confirm:(options:ConfirmOptions)=>Promise<boolean>};
const Context=createContext<DialogApi|null>(null);
export function useDialogs(){const api=useContext(Context);if(!api)throw new Error('内置弹窗服务未初始化。');return api;}

function DialogContent({request,finish}:{request:Request;finish:(result:string|boolean|null)=>void}){
  const [value,setValue]=useState(request.kind==='prompt'?request.options.initialValue||'':'');
  const [error,setError]=useState('');const [pending,setPending]=useState(false);const field=useRef<HTMLInputElement|HTMLTextAreaElement|null>(null);
  const cancel=()=>{if(!pending)finish(request.kind==='prompt'?null:false);};
  useEffect(()=>{field.current?.focus();field.current?.select();},[]);
  async function submit(){
    if(pending)return;
    if(request.kind==='confirm'){finish(true);return;}
    const text=value.trim();const issue=!text?'请填写'+request.options.label+'。':request.options.validate?.(text);
    if(issue){setError(issue);field.current?.focus();return;}
    setPending(true);setError('');
    try{await request.options.onSubmit?.(text);finish(text);}catch(reason){setError(reason instanceof Error?reason.message:String(reason));setPending(false);}
  }
  const footer=<div className="modal-footer"><button type="button" className="secondary-button" disabled={pending} onClick={cancel}>取消</button><button type="submit" className={'primary-button '+(request.options.danger?'danger-button':'')} disabled={pending}>{pending?<Spinner/>:null}{request.options.confirmLabel||(request.kind==='prompt'?'保存':'确认')}</button></div>;
  return <Modal title={request.options.title} subtitle={request.kind==='prompt'?request.options.subtitle:undefined} onClose={cancel} dismissible={!pending} className="input-dialog">
    <form onSubmit={event=>{event.preventDefault();void submit();}}>
      {request.kind==='prompt'?<label className="dialog-field">{request.options.label}{request.options.multiline?<textarea ref={node=>{field.current=node;}} autoFocus rows={6} value={value} maxLength={request.options.maxLength} disabled={pending} onChange={event=>{setValue(event.target.value);setError('');}} onKeyDown={event=>{if(event.nativeEvent.isComposing||event.nativeEvent.keyCode===229)return;if(event.key==='Enter'&&(event.ctrlKey||event.metaKey)){event.preventDefault();void submit();}}}/>:<input ref={node=>{field.current=node;}} autoFocus value={value} maxLength={request.options.maxLength} disabled={pending} onChange={event=>{setValue(event.target.value);setError('');}} onKeyDown={event=>{if(event.key==='Enter'&&(event.nativeEvent.isComposing||event.nativeEvent.keyCode===229))event.preventDefault();}}/>}</label>:<p className="confirmation-text">{request.options.message}</p>}
      {error&&<p className="inline-error" role="alert">{error}</p>}{footer}
    </form>
  </Modal>;
}

export function DialogProvider({children}:{children:ReactNode}){
  const [request,setRequest]=useState<Request|null>(null);const current=useRef<Request|null>(null);const queue=useRef<Request[]>([]);const serial=useRef(0);
  const enqueue=useCallback((item:Request)=>{if(current.current)queue.current.push(item);else{current.current=item;serial.current++;setRequest(item);}},[]);
  const finish=useCallback((result:string|boolean|null)=>{const item=current.current;if(!item)return;if(item.kind==='prompt')item.resolve(typeof result==='string'?result:null);else item.resolve(result===true);const next=queue.current.shift()||null;current.current=next;serial.current++;setRequest(next);},[]);
  const api=useMemo<DialogApi>(()=>({prompt:options=>new Promise(resolve=>enqueue({kind:'prompt',options,resolve})),confirm:options=>new Promise(resolve=>enqueue({kind:'confirm',options,resolve}))}),[enqueue]);
  useEffect(()=>()=>{for(const item of [current.current,...queue.current]){if(item?.kind==='prompt')item.resolve(null);else if(item)item.resolve(false);}current.current=null;queue.current=[];},[]);
  return <Context.Provider value={api}>{children}{request&&<DialogContent key={serial.current} request={request} finish={finish}/>}</Context.Provider>;
}
