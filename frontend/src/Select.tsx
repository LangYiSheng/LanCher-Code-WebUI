import {Children,isValidElement,useEffect,useId,useRef,useState,type CSSProperties,type KeyboardEvent,type OptionHTMLAttributes,type ReactNode} from 'react';
import {createPortal} from 'react-dom';
import {Icon} from './Icon';
import './Select.css';

type Choice={value:string;label:ReactNode;text:string;disabled:boolean};
type Props={children:ReactNode;value?:string|number|readonly string[];defaultValue?:string|number|readonly string[];onChange?:(event:{target:{value:string}})=>void;disabled?:boolean;className?:string;style?:CSSProperties;id?:string;name?:string;title?:string;required?:boolean;'aria-label'?:string;'aria-describedby'?:string;'aria-invalid'?:boolean|'true'|'false'};
function textOf(node:ReactNode):string{return Children.toArray(node).map(item=>typeof item==='string'||typeof item==='number'?String(item):isValidElement<{children?:ReactNode}>(item)?textOf(item.props.children):'').join('');}
function choicesOf(children:ReactNode):Choice[]{
  return Children.toArray(children).flatMap(child=>{
    if(!isValidElement<OptionHTMLAttributes<HTMLOptionElement>>(child))return [];
    if(child.type!=='option')return choicesOf(child.props.children);
    const text=textOf(child.props.children);return [{value:String(child.props.value??text),label:child.props.children,text,disabled:!!child.props.disabled}];
  });
}
// 受控选择器：由 React 呈现选项、键盘选择和边界定位，不调用浏览器原生菜单。
export function Select({children,value,defaultValue,onChange,disabled=false,className='',style,id,name,title,required,'aria-label':label,'aria-describedby':describedBy,'aria-invalid':invalid}:Props){
  const choices=choicesOf(children);const [fallback,setFallback]=useState(String(defaultValue??choices[0]?.value??''));
  const current=String(value??fallback),selected=choices.findIndex(choice=>choice.value===current);
  const [open,setOpen]=useState(false),[active,setActive]=useState(0);const [position,setPosition]=useState({left:8,top:8,width:240,maxHeight:320});
  const trigger=useRef<HTMLButtonElement>(null),menu=useRef<HTMLDivElement>(null);const prefix=useRef({text:'',at:0});const listId=useId();
  const enabled=choices.map((choice,index)=>choice.disabled?-1:index).filter(index=>index>=0);
  function measure(){
    const box=trigger.current?.getBoundingClientRect();if(!box)return;
    const width=Math.min(Math.max(box.width,200),Math.min(420,innerWidth-16));const maxHeight=Math.min(340,innerHeight-24,Math.max(110,choices.length*36+16));
    const top=innerHeight-box.bottom>=maxHeight+8?box.bottom+5:Math.max(8,box.top-maxHeight-5);
    setPosition({left:Math.min(Math.max(8,box.left),innerWidth-width-8),top,width,maxHeight});
  }
  function show(){if(disabled||!enabled.length)return;measure();setActive(selected>=0&&!choices[selected].disabled?selected:enabled[0]);setOpen(true);}
  function choose(index:number){const choice=choices[index];if(!choice||choice.disabled)return;setFallback(choice.value);setOpen(false);trigger.current?.focus();onChange?.({target:{value:choice.value}});}
  function step(delta:number){const index=enabled.indexOf(active);setActive(enabled[(Math.max(0,index)+delta+enabled.length)%enabled.length]);}
  useEffect(()=>{if(disabled)setOpen(false);},[disabled]);
  useEffect(()=>{
    if(!open)return;
    const outside=(event:PointerEvent)=>{if(event.target instanceof Node&&!trigger.current?.contains(event.target)&&!menu.current?.contains(event.target))setOpen(false);};
    document.addEventListener('pointerdown',outside);window.addEventListener('resize',measure);window.addEventListener('scroll',measure,true);
    return()=>{document.removeEventListener('pointerdown',outside);window.removeEventListener('resize',measure);window.removeEventListener('scroll',measure,true);};
  },[open]);
  useEffect(()=>{if(open)menu.current?.querySelector<HTMLElement>('[data-active="true"]')?.scrollIntoView({block:'nearest'});},[open,active]);
  function keydown(event:KeyboardEvent<HTMLButtonElement>){
    if(event.nativeEvent.isComposing||event.nativeEvent.keyCode===229)return;
    if(event.key==='Escape'){if(open){event.preventDefault();setOpen(false);}return;}
    if(event.key==='Tab'){setOpen(false);return;}
    if(['ArrowDown','ArrowUp','Home','End'].includes(event.key)){event.preventDefault();if(!open)show();else if(event.key==='Home')setActive(enabled[0]);else if(event.key==='End')setActive(enabled[enabled.length-1]);else step(event.key==='ArrowDown'?1:-1);return;}
    if(event.key==='Enter'||event.key===' '){event.preventDefault();if(open)choose(active);else show();return;}
    if(event.key.length===1&&!event.ctrlKey&&!event.metaKey&&!event.altKey){
      const now=Date.now();prefix.current={text:now-prefix.current.at>600?event.key:prefix.current.text+event.key,at:now};
      const index=choices.findIndex(choice=>!choice.disabled&&choice.text.toLocaleLowerCase().startsWith(prefix.current.text.toLocaleLowerCase()));
      if(index>=0){event.preventDefault();if(!open)show();setActive(index);}
    }
  }
  const selectedLabel=selected>=0?choices[selected].label:current||'请选择';
  return <span className={'custom-select '+className} style={style}>
    {name&&<input type="hidden" name={name} value={current} disabled={disabled}/>}
    <button ref={trigger} id={id} type="button" className="select-trigger" role="combobox" aria-haspopup="listbox" aria-expanded={open} aria-controls={open?listId:undefined} aria-activedescendant={open?listId+'-'+active:undefined} aria-label={label} aria-describedby={describedBy} aria-invalid={invalid} aria-required={required||undefined} title={title||choices[selected]?.text} disabled={disabled} onClick={()=>open?setOpen(false):show()} onKeyDown={keydown} onBlur={event=>{if(!menu.current?.contains(event.relatedTarget as Node|null))setOpen(false);}}>
      <span className="select-value">{selectedLabel}</span><Icon name="down" size={13}/>
    </button>
    {open&&createPortal(<div ref={menu} id={listId} role="listbox" aria-label={(label||choices[selected]?.text||'选择')+'选项'} className="select-popup" style={position}>
      {choices.map((choice,index)=><div id={listId+'-'+index} key={choice.value+'-'+index} role="option" aria-selected={choice.value===current} aria-disabled={choice.disabled||undefined} data-active={index===active} className={'select-option '+(choice.disabled?'disabled':'')} onMouseDown={event=>event.preventDefault()} onMouseEnter={()=>{if(!choice.disabled)setActive(index);}} onClick={()=>choose(index)}><span>{choice.label}</span>{choice.value===current&&<Icon name="check" size={14}/>}</div>)}
    </div>,trigger.current?.closest('dialog')||document.body)}
  </span>;
}
