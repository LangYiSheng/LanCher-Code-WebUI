import {Children,cloneElement,isValidElement,useEffect,useId,useState,type ReactElement,type ReactNode} from 'react';
import {Select} from './Select';
import {pretty} from './api';
import {Icon} from './Icon';
import type {SettingsEditorDraft} from './settingsDrafts';

type ControlProps={id?:string;'aria-label'?:string;'aria-describedby'?:string};
export function Field({label,note,children}:{label:string;note?:string;children:ReactNode}){
  const generated=useId(),help=generated+'-help';let controlId=generated,assigned=false;
  const controls=Children.map(children,child=>{
    if(!assigned&&isValidElement<ControlProps>(child)&&(['input','textarea'].includes(String(child.type))||child.type===Select||child.type===Numeric)){
      assigned=true;controlId=child.props.id||generated;
      return cloneElement(child as ReactElement<ControlProps>,{id:controlId,'aria-label':child.props['aria-label']||label,'aria-describedby':note?help:child.props['aria-describedby']});
    }
    return child;
  });
  return <div className="settings-field"><div className="setting-field-label"><label htmlFor={controlId}>{label}</label>{note&&<small id={help}>{note}</small>}</div><div className="setting-field-control">{controls}</div></div>;
}
export function Numeric({value,onChange,inherited=false,placeholder,min=0,...attributes}:{value:any;onChange:(value:any)=>void;inherited?:boolean;placeholder?:string;min?:number}&ControlProps){
  return <input {...attributes} type="number" min={min} value={value??''} placeholder={placeholder||(inherited?'继承供应商':'未设置')} onChange={event=>onChange(event.target.value===''?null:Number(event.target.value))}/>;
}
export function Advanced({title='高级设置',note,children}:{title?:string;note?:string;children:ReactNode}){
  return <details className="advanced-settings"><summary><Icon name="settings" size={14}/><span>{title}</span>{note&&<small>{note}</small>}<Icon name="down" size={13}/></summary><div className="advanced-content">{children}</div></details>;
}
export function JsonEditor({label,value,onChange,note,draft,onDraft}:{label:string;value:any;onChange:(value:any)=>void;note?:string;draft?:SettingsEditorDraft;onDraft?:(draft:SettingsEditorDraft)=>void}){
  const source=pretty(value),restored=draft?.source===source?draft:undefined;
  const [text,setText]=useState(restored?.text??source),[error,setError]=useState(restored?.valid===false?'JSON 格式未完成，请修正后保存。':'');const id=useId();
  useEffect(()=>{const saved=draft?.source===source?draft:undefined;setText(saved?.text??source);setError(saved?.valid===false?'JSON 格式未完成，请修正后保存。':'');},[source,draft?.text,draft?.valid,draft?.source]);
  return <div className="settings-json"><label htmlFor={id}>{label}</label>{note&&<p className="small-note">{note}</p>}<textarea id={id} aria-label={label} spellCheck={false} value={text} onChange={event=>{
    const raw=event.target.value;setText(raw);
    try{const parsed=JSON.parse(raw);onChange(parsed);onDraft?.({text:raw,valid:true,source:pretty(parsed)});setError('');}
    catch{onDraft?.({text:raw,valid:false,source});setError('JSON 格式未完成，请修正后保存。');}
  }}/>{error&&<p className="inline-error" role="alert">{error}</p>}</div>;
}
export function SettingSource({label,value}:{label:string;value?:string|number|null}){
  return <div className="setting-source"><span>{label}</span>{value!=null&&<code title={String(value)}>{String(value)}</code>}</div>;
}
