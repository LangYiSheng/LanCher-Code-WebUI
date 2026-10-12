import {useEffect,useMemo,useRef,useState} from 'react';
import type {ChatSummary,Project} from './types';
import {Modal} from './Dialogs';
import {Icon} from './Icon';
import {isBusy,statusLabel} from './api';
import {searchChats} from './chatSearch';
import './ChatSearch.css';

type Props={chats:ChatSummary[];projects:Project[];onClose:()=>void;onSelect:(chat:ChatSummary)=>void};
export function ChatSearch({chats,projects,onClose,onSelect}:Props){
  const [query,setQuery]=useState(''),[activeId,setActiveId]=useState<string|null>(null);
  const matches=useMemo(()=>searchChats(chats,projects,query),[chats,projects,query]),rows=matches.slice(0,100);
  const projectMap=useMemo(()=>new Map(projects.map(project=>[project.id,project])),[projects]);
  const index=Math.max(0,rows.findIndex(chat=>chat.id===activeId)),selected=rows[index];
  const activeRow=useRef<HTMLButtonElement|null>(null),inputRef=useRef<HTMLInputElement|null>(null);
  useEffect(()=>{inputRef.current?.focus();},[]);
  useEffect(()=>{activeRow.current?.scrollIntoView({block:'nearest'});},[index,query]);
  return <Modal title="搜索聊天" subtitle="按聊天标题、项目名称或模型查找。归档记录在设置中查看。" className="chat-search-modal" onClose={onClose}>
    <div className="chat-search-input"><Icon name="search" size={18}/><input ref={inputRef} autoFocus aria-label="搜索聊天关键词" placeholder="搜索标题、项目、模型…" value={query} onChange={event=>{setQuery(event.target.value);setActiveId(null);}} onKeyDown={event=>{
      if(event.nativeEvent.isComposing||event.nativeEvent.keyCode===229)return;
      if(['ArrowDown','ArrowUp'].includes(event.key)&&rows.length){event.preventDefault();setActiveId(rows[(index+(event.key==='ArrowDown'?1:-1)+rows.length)%rows.length].id);}
      if(event.key==='Enter'&&selected){event.preventDefault();onSelect(selected);}
    }}/><kbd>Esc</kbd></div>
    <div className="chat-search-results" aria-label="聊天搜索结果">{rows.map((chat,row)=>{const project=projectMap.get(chat.project_id);return <button key={chat.id} ref={row===index?activeRow:undefined} className={'chat-search-result '+(row===index?'selected':'')} aria-current={row===index?'true':undefined} onMouseMove={()=>setActiveId(chat.id)} onClick={()=>onSelect(chat)}>
      <Icon name={chat.pinned?'pin':'chat'} size={17}/><span><strong>{chat.title||'未命名聊天'}</strong><small>{project?.name} · {chat.model_ref}</small></span>{isBusy(chat.status)&&<span className="chat-search-running">{statusLabel(chat.status)}</span>}<Icon name="chevron" size={13}/>
    </button>;})}{!rows.length&&<div className="chat-search-empty"><Icon name="chat" size={24}/><p>{query.trim()?'没有找到符合条件的聊天。':'还没有正式聊天，发送第一条消息后会出现在这里。'}</p></div>}</div>
    <footer className="chat-search-footer"><span>{matches.length>100?'显示前 100 项，继续输入可缩小范围':matches.length+' 个聊天'}</span><span>↑↓ 选择 · Enter 打开</span></footer>
  </Modal>;
}
