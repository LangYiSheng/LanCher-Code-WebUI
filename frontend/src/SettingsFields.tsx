import {Children,cloneElement,isValidElement,useEffect,useId,useRef,useState,type ReactElement,type ReactNode} from 'react';
import {Select} from './Select';
import {pretty} from './api';
import {Icon} from './Icon';
import type {SettingsEditorDraft} from './settingsDrafts';
import {useFieldValidation,validationPathKey,type ValidationPathInput} from './settingsValidation';

type ControlProps={id?:string;'aria-label'?:string;'aria-describedby'?:string;'aria-invalid'?:boolean;required?:boolean};
export function Field({label,note,children,path,required,error}:{label:string;note?:string;children:ReactNode;path?:ValidationPathInput;required?:boolean;error?:string}){
  const validation=useFieldValidation(path),message=error||(path!==undefined||validation.path.length?validation.issues.map(issue=>issue.message).join(' '):'');
  const generated=useId(),help=generated+'-help',errorId=generated+'-error';let controlId=generated,assigned=false;
  const controls=Children.map(children,child=>{
    if(!assigned&&isValidElement<ControlProps>(child)&&(['input','textarea'].includes(String(child.type))||child.type===Select||child.type===Numeric)){
      assigned=true;controlId=child.props.id||generated;
      const describedBy=[child.props['aria-describedby'],note?help:undefined,message?errorId:undefined].filter(Boolean).join(' ')||undefined;
      return cloneElement(child as ReactElement<ControlProps>,{id:controlId,'aria-label':child.props['aria-label']||label,'aria-describedby':describedBy,'aria-invalid':message?true:undefined,required:required||child.props.required});
    }
    return child;
  });
  return <div className="settings-field" data-setting-path={path!==undefined||validation.path.length?validationPathKey(validation.domain,validation.path):undefined} data-invalid={message?'true':undefined}><div className="setting-field-label"><label htmlFor={controlId}>{label}{required&&<span className="setting-required" aria-hidden="true"> *</span>}</label>{note&&<small id={help}>{note}</small>}</div><div className="setting-field-control">{controls}{message&&<p id={errorId} className="inline-error" role="alert">{message}</p>}</div></div>;
}
export function Numeric({value,onChange,inherited=false,placeholder,min=0,...attributes}:{value:any;onChange:(value:any)=>void;inherited?:boolean;placeholder?:string;min?:number}&ControlProps){
  const displayed=typeof value==='number'||typeof value==='string'?value:'';
  return <input {...attributes} type="number" min={min} value={displayed} placeholder={placeholder||(inherited?'继承供应商':'未设置')} onChange={event=>onChange(event.target.value===''?null:Number(event.target.value))}/>;
}
export function Advanced({title='高级设置',note,children}:{title?:string;note?:string;children:ReactNode}){
  const ref=useRef<HTMLDetailsElement>(null),validation=useFieldValidation();
  useEffect(()=>{if(ref.current?.querySelector('[data-invalid="true"],[aria-invalid="true"]'))ref.current.open=true;},[children,validation.issues]);
  return <details ref={ref} className="advanced-settings"><summary><Icon name="settings" size={14}/><span>{title}</span>{note&&<small>{note}</small>}<Icon name="down" size={13}/></summary><div className="advanced-content">{children}</div></details>;
}
export function JsonEditor({label,value,onChange,note,draft,onDraft,path}:{label:string;value:any;onChange:(value:any)=>void;note?:string;draft?:SettingsEditorDraft;onDraft?:(draft:SettingsEditorDraft)=>void;path?:ValidationPathInput}){
  const validation=useFieldValidation(path);
  const source=pretty(value),restored=draft?.source===source?draft:undefined;
  const [text,setText]=useState(restored?.text??source),[error,setError]=useState(restored?.valid===false?'JSON 格式未完成，请修正后保存。':'');const id=useId();
  useEffect(()=>{const saved=draft?.source===source?draft:undefined;setText(saved?.text??source);setError(saved?.valid===false?'JSON 格式未完成，请修正后保存。':'');},[source,draft?.text,draft?.valid,draft?.source]);
  const message=error||(path!==undefined||validation.path.length?validation.issues.map(issue=>issue.message).join(' '):''),errorId=id+'-error';
  return <div className="settings-json" data-setting-path={path!==undefined||validation.path.length?validationPathKey(validation.domain,validation.path):undefined} data-invalid={message?'true':undefined}><label htmlFor={id}>{label}</label>{note&&<p className="small-note">{note}</p>}<textarea id={id} aria-label={label} aria-invalid={message?true:undefined} aria-describedby={message?errorId:undefined} spellCheck={false} value={text} onChange={event=>{
    const raw=event.target.value;setText(raw);
    try{const parsed=JSON.parse(raw);onChange(parsed);onDraft?.({text:raw,valid:true,source:pretty(parsed)});setError('');}
    catch{onDraft?.({text:raw,valid:false,source});setError('JSON 格式未完成，请修正后保存。');}
  }}/>{message&&<p id={errorId} className="inline-error" role="alert">{message}</p>}</div>;
}
export function SettingSource({label,value}:{label:string;value?:string|number|null}){
  return <div className="setting-source"><span>{label}</span>{value!=null&&<code title={String(value)}>{String(value)}</code>}</div>;
}
