import type {FileEntry} from './types';

export type FileScope='files'|'changes';
export type ChangeStatus='added'|'modified'|'deleted';
export const changeLabels:Record<ChangeStatus,string>={added:'新增',modified:'修改',deleted:'删除'};

// 项目源码可在对话之间沿用；变更选择只属于生成基线的那个对话。
export function fileScopeKey(scope:FileScope,projectId:string,chatId?:string):string {
  return scope==='changes'?JSON.stringify([scope,projectId,chatId||'']):JSON.stringify([scope,projectId]);
}
export function fileListUrl(scope:FileScope,projectId:string,chatId:string|undefined,query:string):string {
  if(scope==='changes'&&!chatId)return '';
  const params=new URLSearchParams({scope,q:query});
  if(scope==='changes')params.set('chat_id',chatId!);
  return '/api/projects/'+encodeURIComponent(projectId)+'/files?'+params.toString();
}
export function filePreviewUrl(scope:FileScope,projectId:string,chatId:string|undefined,path:string):string {
  if(!path||scope==='changes'&&!chatId)return '';
  const owner=scope==='changes'?'/api/chats/'+encodeURIComponent(chatId!):'/api/projects/'+encodeURIComponent(projectId);
  return owner+'/file?path='+encodeURIComponent(path);
}
export function isChangeStatus(status:unknown):status is ChangeStatus {
  return status==='added'||status==='modified'||status==='deleted';
}
export function fileEntries(scope:FileScope,rows:FileEntry[]):FileEntry[] {
  return rows.filter(row=>scope==='changes'?isChangeStatus(row.status):row.status!=='deleted');
}
export type InspectorTab='files'|'changes'|'activity'|'processes'|'usage'|'extensions';
export const inspectorTabTypes:Record<InspectorTab,{title:string;icon:string}>={
  files:{title:'项目文件',icon:'folder'},changes:{title:'对话变更',icon:'edit'},
  activity:{title:'运行',icon:'activity'},processes:{title:'进程',icon:'process'},
  usage:{title:'用量',icon:'activity'},extensions:{title:'扩展',icon:'link'},
};
export type FileSelection={path:string;query:string;collapsed:string[]};
export type InspectorView={tabs:InspectorTab[];active:InspectorTab;newTab:boolean;lastOpenNonce:number;files:FileSelection;changes:FileSelection};
export function isInspectorTab(value:unknown):value is InspectorTab {
  return typeof value==='string'&&Object.hasOwn(inspectorTabTypes,value);
}
export function restoreInspectorView(value:unknown,legacyTab:unknown=undefined,legacyPath=''):InspectorView {
  const raw=value&&typeof value==='object'?value as Record<string,unknown>:null;
  const tabs=raw&&Array.isArray(raw.tabs)?[...new Set(raw.tabs.filter(isInspectorTab))]:[] as InspectorTab[];
  const active=raw&&isInspectorTab(raw.active)?raw.active:isInspectorTab(legacyTab)?legacyTab:'files';
  if(!raw&&isInspectorTab(legacyTab)&&!tabs.includes(active))tabs.push(active);
  const selection=(candidate:unknown,path=''):FileSelection=>{
    const item=candidate&&typeof candidate==='object'?candidate as Record<string,unknown>:{};
    return {path:typeof item.path==='string'?item.path:path,query:typeof item.query==='string'?item.query.slice(0,300):'',
      collapsed:Array.isArray(item.collapsed)?item.collapsed.filter((entry):entry is string=>typeof entry==='string'):[]};
  };
  return {tabs,active:tabs.includes(active)||!tabs.length?active:tabs[0],newTab:!tabs.length||raw?.newTab===true,
    lastOpenNonce:typeof raw?.lastOpenNonce==='number'&&Number.isSafeInteger(raw.lastOpenNonce)&&raw.lastOpenNonce>=0?raw.lastOpenNonce:0,
    files:selection(raw?.files,legacyPath),changes:selection(raw?.changes)};
}
export type FileTreeNode={name:string;path:string;file?:FileEntry;children:FileTreeNode[]};
export function fileTree(rows:FileEntry[]):FileTreeNode[] {
  const roots:FileTreeNode[]=[];
  for(const file of rows){
    const parts=file.path.split('/');let nodes=roots;let path='';
    parts.forEach((name,index)=>{
      path=path?path+'/'+name:name;
      let node=nodes.find(item=>item.name===name);
      if(!node){node={name,path,children:[]};nodes.push(node);}
      if(index===parts.length-1)node.file=file;
      else nodes=node.children;
    });
  }
  const sort=(nodes:FileTreeNode[])=>{
    nodes.sort((a,b)=>Number(!!a.file)-Number(!!b.file)||a.name.localeCompare(b.name,'zh-CN'));
    nodes.forEach(node=>sort(node.children));
  };
  sort(roots);return roots;
}
export function parentDirectories(path:string):string[] {
  const parts=path.split('/');return parts.slice(0,-1).map((_,index)=>parts.slice(0,index+1).join('/'));
}