import type {CSSProperties} from 'react';
import {
  Activity, Archive, ArrowLeft, ArrowUp, BookOpen, Check, ChevronDown,
  ChevronRight, CircleHelp, Clock, CodeXml, Command, Copy, File, FilePenLine,
  FileSearch, FileText, FileX, Folder, FolderSearch, Globe, History,
  Info, Keyboard, Layers, List, ListTodo, LogOut, Logs, Menu, MessageSquare, Monitor, Moon, MoreHorizontal,
  PanelRight, Pencil, Pin, Play, Plug, Plus, RefreshCw, Search, Settings,
  ShieldCheck, Sparkles, Square, Sun, Terminal, Trash2, X,
  type LucideIcon,
} from 'lucide-react';

// 使用静态导入，生产构建只包含工作台实际使用的图标。
const icons:Record<string,LucideIcon>={
  plus:Plus,close:X,chevron:ChevronRight,down:ChevronDown,folder:Folder,
  chat:MessageSquare,search:Search,settings:Settings,panel:PanelRight,
  arrow:ArrowUp,stop:Square,play:Play,more:MoreHorizontal,check:Check,
  copy:Copy,code:CodeXml,terminal:Terminal,file:File,activity:Activity,
  moon:Moon,sun:Sun,monitor:Monitor,shield:ShieldCheck,archive:Archive,
  pin:Pin,refresh:RefreshCw,link:Plug,history:History,command:Command,
  edit:Pencil,trash:Trash2,back:ArrowLeft,globe:Globe,spark:Sparkles,
  menu:Menu,info:Info,read:FileText,write:FilePenLine,delete:FileX,
  glob:FolderSearch,grep:FileSearch,plan:ListTodo,skill:BookOpen,
  process:Terminal,process_list:List,process_read:Logs,process_wait:Clock,
  process_write:Keyboard,process_stop:Square,process_background:Layers,mcp:Plug,unknown:CircleHelp,exit:LogOut,
};
// 本地工具与延迟发现的 MCP 工具共用映射，调用和结果使用同一语义图标。
export function toolIconName(name=''):string {
  const tool=name.toLowerCase();
  if(tool==='tool_search')return 'search';
  if(['process_list','process_read','process_wait','process_write','process_stop','process_background'].includes(tool))return tool;
  if(/^(mcp[._:/-])/.test(tool)||tool.includes('__'))return 'mcp';
  if(tool==='glob'||tool.includes('glob'))return 'glob';
  if(tool==='grep'||tool.includes('grep')||tool==='search_files')return 'grep';
  if(tool.includes('skill'))return 'skill';
  if(tool.includes('plan'))return 'plan';
  if(tool.includes('process')||tool.includes('command')||tool.includes('terminal'))return 'terminal';
  if(tool.includes('delete')||tool.includes('remove'))return 'delete';
  if(tool.includes('edit')||tool.includes('patch')||tool.includes('replace'))return 'edit';
  if(tool.includes('write')||tool.includes('create'))return 'write';
  if(tool.includes('read')||tool.includes('view'))return 'read';
  if(tool.includes('list')||tool.includes('directory'))return 'folder';
  if(tool.includes('fetch')||tool.includes('web'))return 'globe';
  return 'code';
}
const commandIcons:Record<string,string>={discuss:'chat',plan:'plan',do:'play',session:'history',sessions:'history',tasks:'terminal',skills:'skill',mcp:'mcp',model:'globe',access:'shield',compact:'archive',settings:'settings',status:'activity',exit:'exit',help:'unknown'};
// 参数补全沿用当前根命令的图标；根命令列表则按每条候选自身取图标。
export function commandIconName(text:string,candidate=''):string {
  const typed=text.trimStart().match(/^\/([\w-]+)(?:\s|$)/)?.[1];
  if(typed&&commandIcons[typed])return commandIcons[typed];
  const root=candidate.trimStart().replace(/^\//,'').split(/[\s.:/]/)[0];
  return commandIcons[root]||'command';
}
export function Icon({name,size=18,className='',style}:{name:string;size?:number;className?:string;style?:CSSProperties}){
  const Component=icons[name]||icons.code;
  return <Component size={size} strokeWidth={1.65} className={className} style={style} aria-hidden="true" focusable="false"/>;
}
export function Spinner(){return <span className="spinner" aria-label="正在加载"/>;}
