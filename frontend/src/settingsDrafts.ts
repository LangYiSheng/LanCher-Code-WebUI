import {useSyncExternalStore} from 'react';
import type {Dict} from './types';

export type SettingsDomain = 'web'|'ui'|'models'|'runtime'|'execution'|'mcp'|'rules';
export type SettingsScope = 'global'|'project'|'user';
export type SettingsDraftKey = {domain:SettingsDomain;scope?:SettingsScope;projectId?:string};
export type SettingsSnapshot = Dict & {revision?:string;preferences?:Dict};
export type SettingsEditorDraft = {text:string;valid:boolean;source:string};
export type SettingsDraftEntry = {
  key:SettingsDraftKey;value:any;baseline:any;dirty:boolean;saving:boolean;
  error:string;conflict:boolean;revision:string;latestRevision:string;
  editVersion:number;lastSave:Dict|null;editors:Record<string,SettingsEditorDraft>;invalidEditors:string[];
};
export type SettingsSaveTicket = {
  token:number;key:SettingsDraftKey;payload:Dict;value:any;editVersion:number;revision:string;editors:Record<string,SettingsEditorDraft>;
};
export type SettingsSession = {projectId?:string;snapshot:SettingsSnapshot;revision:string};

const GLOBAL_DOMAINS:SettingsDomain[]=['web','ui','models','runtime','execution','mcp','rules'];
const INDICATORS=new Set(['api_key_configured','api_key_template','env_configured','env_template','headers_configured','headers_template']);
const CONFLICT='配置已更新，当前草稿已保留。请确认后重新读取当前页；其他页面的草稿不会丢失。';
const clone=<T,>(value:T):T=>structuredClone(value);
const object=(value:any):value is Dict=>!!value&&typeof value==='object'&&!Array.isArray(value);

function equal(left:any,right:any):boolean {
  if(Object.is(left,right))return true;
  if(Array.isArray(left)&&Array.isArray(right))return left.length===right.length&&left.every((value,index)=>equal(value,right[index]));
  if(!object(left)||!object(right))return false;
  const keys=Object.keys(left);
  return keys.length===Object.keys(right).length&&keys.every(key=>Object.hasOwn(right,key)&&equal(left[key],right[key]));
}
function freeze<T>(value:T):T {
  if(value&&typeof value==='object'){
    for(const nested of Object.values(value))freeze(nested);
    Object.freeze(value);
  }
  return value;
}
function canonical(key:SettingsDraftKey):SettingsDraftKey {
  if(!GLOBAL_DOMAINS.includes(key.domain))throw new Error('未知设置页面。');
  let scope:SettingsScope=key.scope||'global';
  if(key.domain==='rules'&&scope==='global')scope='user';
  if(key.domain==='mcp'||key.domain==='rules'){
    if(!['project',key.domain==='rules'?'user':'global'].includes(scope))throw new Error('设置作用范围无效。');
    if(scope==='project'){
      if(!key.projectId)throw new Error('请先选择项目。');
      return {domain:key.domain,scope,projectId:key.projectId};
    }
  }else if(scope!=='global')throw new Error('这项设置只支持全局作用范围。');
  // 全局配置只有一份草稿，不因用户切换工作项目复制或改变身份。
  return {domain:key.domain,scope};
}
export function settingsDraftId(key:SettingsDraftKey):string {
  const value=canonical(key);
  return JSON.stringify([value.domain,value.scope,value.projectId||null]);
}
function contextId(projectId?:string):string{return projectId||'';}

// 读取来源永远脱敏；用户刚输入的密钥仅存在 edit() 的内存草稿中。
function sanitizeSnapshot(snapshot:SettingsSnapshot):SettingsSnapshot {
  const result=clone(snapshot);
  for(const provider of Object.values(result.config?.providers||{}) as Dict[]){
    if(Object.hasOwn(provider,'api_key'))provider.api_key='';
    for(const model of Object.values(provider.models||{}) as Dict[]){
      if(Object.hasOwn(model,'api_key')&&model.api_key!==null)model.api_key='';
    }
  }
  for(const scope of ['global_mcp','project_mcp']){
    for(const server of Object.values(result[scope]||{}) as Dict[]){
      for(const name of ['env','headers']){
        if(object(server[name]))server[name]=Object.fromEntries(Object.keys(server[name]).map(key=>[key,'']));
      }
    }
  }
  return freeze(result);
}
function domainValue(snapshot:SettingsSnapshot,key:SettingsDraftKey):any {
  switch(key.domain){
    case 'models':return {providers:clone(snapshot.config?.providers||{}),default_model:snapshot.config?.default_model||''};
    case 'web':return clone(snapshot.preferences||{});
    case 'ui':case 'runtime':case 'execution':return clone(snapshot.config?.[key.domain]||{});
    case 'mcp':return clone(key.scope==='project'?snapshot.project_mcp||{}:snapshot.global_mcp||{});
    case 'rules':return clone(key.scope==='project'?snapshot.project_rules||[]:snapshot.user_rules||[]);
  }
}
function payloadValue(value:any):any {
  if(Array.isArray(value))return value.map(payloadValue);
  if(object(value))return Object.fromEntries(Object.entries(value).filter(([key])=>!INDICATORS.has(key)).map(([key,item])=>[key,payloadValue(item)]));
  return value;
}
// 仅将提交后继续编辑的差异覆盖到服务端确认值，避免重发已提交的密钥。
function rebase(submitted:any,current:any,acknowledged:any):any {
  if(equal(submitted,current))return clone(acknowledged);
  if(!object(submitted)||!object(current))return clone(current);
  const result=object(acknowledged)?clone(acknowledged):{};
  for(const key of new Set([...Object.keys(submitted),...Object.keys(current)])){
    const before=Object.hasOwn(submitted,key),after=Object.hasOwn(current,key);
    if(before&&!after)delete result[key];
    else if(after&&!before)result[key]=clone(current[key]);
    else if(!equal(submitted[key],current[key]))result[key]=rebase(submitted[key],current[key],result[key]);
  }
  return result;
}
function errorText(error:unknown):string {
  return error instanceof Error?error.message:typeof error==='string'?error:'设置保存未成功，请重试。';
}

export class SettingsDraftConflictError extends Error {
  status=409;
  constructor(message=CONFLICT){super(message);this.name='SettingsDraftConflictError';}
}

export class SettingsDraftStore {
  private entries=new Map<string,SettingsDraftEntry>();
  private sessions=new Map<string,SettingsSession>();
  private pending=new Map<string,SettingsSaveTicket>();
  private listeners=new Set<()=>void>();
  private version=0;
  private serial=0;

  // 稳定订阅函数可直接用于 useSyncExternalStore，不依赖设置页是否挂载。
  subscribe=(listener:()=>void)=>{this.listeners.add(listener);return ()=>{this.listeners.delete(listener);};};
  getSnapshot=()=>this.version;
  private publish(){this.version++;for(const listener of [...this.listeners])listener();}
  private source(key:SettingsDraftKey){return this.sessions.get(contextId(key.scope==='project'?key.projectId:undefined));}
  private fresh(key:SettingsDraftKey):SettingsDraftEntry|undefined {
    const source=this.source(key);if(!source)return undefined;
    const value=domainValue(source.snapshot,key);
    return freeze({key:clone(key),value:clone(value),baseline:clone(value),dirty:false,saving:false,error:'',
      conflict:false,revision:source.revision,latestRevision:source.revision,editVersion:0,lastSave:null,editors:{},invalidEditors:[]});
  }
  private put(key:SettingsDraftKey,value:SettingsDraftEntry){
    const invalidEditors=Object.keys(value.editors).filter(name=>!value.editors[name].valid);
    this.entries.set(settingsDraftId(key),freeze({...value,invalidEditors,dirty:!equal(value.value,value.baseline)||invalidEditors.length>0}));
  }

  getSession(projectId?:string):SettingsSession|undefined {return this.sessions.get(contextId(projectId));}
  get(key:SettingsDraftKey):SettingsDraftEntry|undefined {
    const normalized=canonical(key),id=settingsDraftId(normalized);
    let entry=this.entries.get(id);
    if(!entry){entry=this.fresh(normalized);if(entry)this.entries.set(id,entry);}
    return entry;
  }
  list():SettingsDraftEntry[]{return [...this.entries.values()];}

  receive(snapshot:SettingsSnapshot,projectId?:string):void {
    // 全局来源必须是无 project_id 的 GET；项目来源只更新该项目 MCP 与权限页。
    const source=sanitizeSnapshot(snapshot),revision=source.revision||'';
    this.sessions.set(contextId(projectId),freeze({...(projectId?{projectId}:{}),snapshot:source,revision}));
    for(const entry of this.entries.values()){
      const key=entry.key;
      if(projectId?key.scope!=='project'||key.projectId!==projectId:key.scope==='project')continue;
      const incoming=domainValue(source,key);
      if(entry.dirty||entry.saving){
        const changed=key.domain==='web'?!equal(entry.baseline,incoming):entry.revision!==revision;
        const conflict=entry.conflict||changed;
        this.put(key,{...entry,latestRevision:revision,conflict,error:conflict?CONFLICT:entry.error});
      }else{
        this.put(key,{...entry,value:clone(incoming),baseline:clone(incoming),revision,latestRevision:revision,
          dirty:false,conflict:false,error:''});
      }
    }
    this.publish();
  }

  edit(key:SettingsDraftKey,value:any|((previous:any)=>any)):void {
    const entry=this.get(key);if(!entry)throw new Error('请先读取这项设置。');
    const next=typeof value==='function'?value(clone(entry.value)):value;
    this.put(entry.key,{...entry,value:clone(next),dirty:!equal(next,entry.baseline),editVersion:entry.editVersion+1,
      error:entry.conflict?entry.error:''});
    this.publish();
  }

  getEditor(key:SettingsDraftKey,name:string):SettingsEditorDraft|undefined {return this.get(key)?.editors[name];}
  setEditor(key:SettingsDraftKey,name:string,draft:SettingsEditorDraft|undefined):void {
    const entry=this.get(key);if(!entry)throw new Error('请先读取这项设置。');
    const editors={...entry.editors};
    if(draft===undefined)delete editors[name];else editors[name]=clone(draft);
    this.put(entry.key,{...entry,editors,editVersion:entry.editVersion+1,error:entry.conflict?entry.error:''});this.publish();
  }

  beginSave(key:SettingsDraftKey):SettingsSaveTicket {
    const entry=this.get(key);if(!entry)throw new Error('请先读取这项设置。');
    if(entry.saving)throw new Error('当前页正在保存，请等待完成。');
    if(entry.invalidEditors.length)throw new Error('当前页还有未完成的 JSON，请修正后保存。');
    if(entry.conflict)throw new SettingsDraftConflictError();
    if(entry.key.domain!=='web'&&!entry.revision)throw new Error('配置版本尚未加载，请重新读取当前页。');
    const payload:Dict={domain:entry.key.domain,scope:entry.key.scope,data:payloadValue(entry.value)};
    if(entry.key.domain!=='web')payload.revision=entry.revision;
    if(entry.key.scope==='project')payload.project_id=entry.key.projectId;
    const ticket=freeze({token:++this.serial,key:clone(entry.key),payload,value:clone(entry.value),
      editVersion:entry.editVersion,revision:entry.revision,editors:clone(entry.editors)});
    this.pending.set(settingsDraftId(entry.key),ticket);
    this.put(entry.key,{...entry,saving:true,error:''});this.publish();
    return ticket;
  }

  saved(ticket:SettingsSaveTicket,response:Dict):boolean {
    const id=settingsDraftId(ticket.key),active=this.pending.get(id),entry=this.entries.get(id);
    if(!entry||active?.token!==ticket.token)return false;
    if(response.saved===false)throw new Error('服务端未确认设置保存，请重试。');
    const source=this.source(entry.key);
    const incoming=object(response.snapshot)?response.snapshot:undefined;
    const revision=typeof response.revision==='string'?response.revision:incoming?.revision||source?.revision||ticket.revision;
    const stale=!!source&&ticket.key.domain!=='web'&&source.revision!==ticket.revision&&source.revision!==revision;
    this.pending.delete(id);
    if(stale){
      // 较新外部读取已到达时，迟到的保存响应不能回滚最新来源或清掉冲突草稿。
      this.put(entry.key,{...entry,saving:false,conflict:true,error:CONFLICT,lastSave:clone(response)});
      this.publish();return true;
    }
    let snapshot:SettingsSnapshot=clone(source?.snapshot||{});
    if(incoming)snapshot={...snapshot,...clone(incoming),revision};
    if(entry.key.domain==='web'&&object(response.preferences))snapshot.preferences=clone(response.preferences);
    snapshot=sanitizeSnapshot(snapshot);
    const acknowledged=incoming||entry.key.domain==='web'&&object(response.preferences)
      ?domainValue(snapshot,entry.key):clone(ticket.value);
    const value=rebase(ticket.value,entry.value,acknowledged);
    const editors=Object.fromEntries(Object.entries(entry.editors).filter(([name,draft])=>!equal(draft,ticket.editors[name])));
    // 自己已确认的保存只推进同来源版本；项目组合版本不能套到全局，反之亦然。
    if(incoming||entry.key.domain==='web'){
      this.sessions.set(contextId(entry.key.projectId),freeze({...(entry.key.projectId?{projectId:entry.key.projectId}:{}),snapshot,revision}));
      for(const other of this.entries.values()){
        if(settingsDraftId(other.key)===id||contextId(other.key.projectId)!==contextId(entry.key.projectId))continue;
        if(other.dirty||other.saving){
          const eligible=!other.conflict&&other.revision===ticket.revision;
          this.put(other.key,{...other,latestRevision:revision,...(eligible?{revision}:{}),conflict:other.conflict});
        }else{
          const next=domainValue(snapshot,other.key);
          this.put(other.key,{...other,value:clone(next),baseline:clone(next),revision,latestRevision:revision,error:'',conflict:false});
        }
      }
    }
    this.put(entry.key,{...entry,value,editors,baseline:clone(acknowledged),dirty:!equal(value,acknowledged),
      saving:false,error:'',conflict:false,revision,latestRevision:revision,lastSave:clone(response)});
    this.publish();return true;
  }

  failed(ticket:SettingsSaveTicket,error:unknown):boolean {
    const id=settingsDraftId(ticket.key),entry=this.entries.get(id);
    if(!entry||this.pending.get(id)?.token!==ticket.token)return false;
    this.pending.delete(id);
    const conflict=entry.conflict||!!error&&typeof error==='object'&&'status' in error&&error.status===409;
    this.put(entry.key,{...entry,saving:false,error:errorText(error),conflict});this.publish();return true;
  }

  reload(key:SettingsDraftKey,options:{confirmed?:boolean}={}):void {
    const entry=this.get(key);if(!entry)throw new Error('请先读取这项设置。');
    if(entry.saving)throw new Error('当前页正在保存，请等待完成后重新读取。');
    if((entry.dirty||entry.conflict)&&!options.confirmed)throw new Error('重新读取会丢弃当前页草稿，请先确认。');
    const fresh=this.fresh(entry.key);if(!fresh)throw new Error('请先读取最新配置。');
    this.put(entry.key,{...fresh,editVersion:entry.editVersion+1});this.publish();
  }
}

// 放在 App 的 store 实例中保存；设置页卸载不会销毁草稿，也不会把密钥写到浏览器存储。
export function useSettingsDrafts(store:SettingsDraftStore):SettingsDraftStore {
  useSyncExternalStore(store.subscribe,store.getSnapshot,store.getSnapshot);
  return store;
}
