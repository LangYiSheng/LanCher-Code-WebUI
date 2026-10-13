import {useSyncExternalStore} from 'react';
import type {Dict} from './types';
import {normalizeValidationIssues,valueAtValidationPath,type ValidationIssue} from './settingsValidation.ts';

export type SettingsDomain = 'web'|'ui'|'models'|'runtime'|'execution'|'mcp'|'rules';
export type SettingsScope = 'global'|'project'|'user';
export type SettingsDraftKey = {domain:SettingsDomain;scope?:SettingsScope;projectId?:string};
export type SettingsSnapshot = Dict & {revision?:string;preferences?:Dict};
export type SettingsEditorDraft = {text:string;valid:boolean;source:string};
export type SettingsDraftEntry = {
  key:SettingsDraftKey;value:any;baseline:any;dirty:boolean;saving:boolean;
  error:string;issues:ValidationIssue[];blocked:boolean;conflict:boolean;revision:string;latestRevision:string;
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
    if(!object(provider))continue;
    if(Object.hasOwn(provider,'api_key'))provider.api_key='';
    for(const model of Object.values(provider.models||{}) as Dict[]){
      if(!object(model))continue;
      if(Object.hasOwn(model,'api_key')&&model.api_key!==null)model.api_key='';
    }
  }
  for(const scope of ['global_mcp','project_mcp']){
    for(const server of Object.values(result[scope]||{}) as Dict[]){
      if(!object(server))continue;
      for(const name of ['env','headers']){
        if(object(server[name]))server[name]=Object.fromEntries(Object.keys(server[name]).map(key=>[key,'']));
      }
    }
  }
  return freeze(result);
}
function domainValue(snapshot:SettingsSnapshot,key:SettingsDraftKey):any {
  switch(key.domain){
    case 'models':return snapshot.config&&Object.hasOwn(snapshot.config,'providers')&&Object.hasOwn(snapshot.config,'default_model')
      ?{providers:clone(snapshot.config.providers),default_model:snapshot.config.default_model}:undefined;
    case 'web':return clone(snapshot.preferences);
    case 'ui':case 'runtime':case 'execution':return clone(snapshot.config?.[key.domain]);
    case 'mcp':return clone(key.scope==='project'?snapshot.project_mcp:snapshot.global_mcp);
    case 'rules':return clone(key.scope==='project'?snapshot.project_rules:snapshot.user_rules);
  }
}
function domainSource(key:SettingsDraftKey):string {
  if(key.domain==='mcp')return key.scope==='project'?'project_mcp':'global_mcp';
  if(key.domain==='rules')return key.scope==='project'?'project_rules':'user_rules';
  return key.domain;
}
function sourceStatus(snapshot:SettingsSnapshot,key:SettingsDraftKey){
  const issues=normalizeValidationIssues(snapshot.domain_errors?.[domainSource(key)]);
  const blocked=domainValue(snapshot,key)===undefined;
  return {issues,blocked,error:issues.map(issue=>issue.message).join(' ')||(blocked?'这项设置尚未能读取，请修复配置后重新读取。':'')};
}
function mergeSourceIssues(existing:ValidationIssue[],incoming:ValidationIssue[],sourceValue:any,currentValue:any):ValidationIssue[]{
  const relevant=incoming.filter(issue=>equal(valueAtValidationPath(sourceValue,issue.path),valueAtValidationPath(currentValue,issue.path)));
  return [...existing.filter(issue=>!relevant.some(item=>item.domain===issue.domain&&equal(item.path,issue.path))),...relevant];
}
function mergeSnapshot(previous:SettingsSnapshot,incoming:SettingsSnapshot,revision:string):SettingsSnapshot {
  const result:SettingsSnapshot={...clone(previous),...clone(incoming),revision};
  for(const source of Object.keys(incoming.domain_errors||{})){
    if(!normalizeValidationIssues(incoming.domain_errors[source]).length)continue;
    if(['global_mcp','project_mcp','user_rules','project_rules'].includes(source)){
      if(!Object.hasOwn(incoming,source))delete result[source];
    }else if(['models','ui','runtime','execution'].includes(source)&&object(result.config)){
      for(const field of source==='models'?['providers','default_model']:[source]){
        if(!object(incoming.config)||!Object.hasOwn(incoming.config,field))delete result.config[field];
      }
    }
  }
  return result;
}
function errorIssues(error:unknown):ValidationIssue[]{
  if(!error||typeof error!=='object')return [];
  const data='data' in error&&object(error.data)?error.data:error;
  return normalizeValidationIssues('issues' in data?data.issues:'detail' in data&&object(data.detail)?data.detail.issues:undefined);
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
    const value=domainValue(source.snapshot,key),status=sourceStatus(source.snapshot,key);
    return freeze({key:clone(key),value:clone(value),baseline:clone(value),dirty:false,saving:false,...status,
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
      const incoming=domainValue(source,key),status=sourceStatus(source,key);
      if(status.blocked){
        // 读取失败没有新基线；保留已有值与未保存草稿，禁止把空值当成可保存配置。
        this.put(key,{...entry,...status,latestRevision:revision});continue;
      }
      if(entry.dirty||entry.saving){
        const changed=key.domain==='web'?!equal(entry.baseline,incoming):entry.revision!==revision;
        const conflict=entry.conflict||changed;
        const issues=mergeSourceIssues(entry.blocked?[]:entry.issues,status.issues,incoming,entry.value);
        this.put(key,{...entry,blocked:false,issues,latestRevision:revision,conflict,error:conflict?CONFLICT:issues.length?status.error||entry.error:entry.blocked?'':entry.error});
      }else{
        this.put(key,{...entry,value:clone(incoming),baseline:clone(incoming),revision,latestRevision:revision,
          dirty:false,...status,conflict:false});
      }
    }
    this.publish();
  }

  edit(key:SettingsDraftKey,value:any|((previous:any)=>any)):void {
    const entry=this.get(key);if(!entry)throw new Error('请先读取这项设置。');
    const next=typeof value==='function'?value(clone(entry.value)):value;
    const issues=entry.issues.filter(issue=>equal(valueAtValidationPath(entry.value,issue.path),valueAtValidationPath(next,issue.path)));
    this.put(entry.key,{...entry,value:clone(next),dirty:!equal(next,entry.baseline),editVersion:entry.editVersion+1,
      issues,error:entry.conflict||entry.blocked?entry.error:issues.length?entry.error:''});
    this.publish();
  }

  setIssues(key:SettingsDraftKey,issues:ValidationIssue[]):void {
    const entry=this.get(key);if(!entry)throw new Error('请先读取这项设置。');
    const current=normalizeValidationIssues(issues).filter(issue=>issue.domain===entry.key.domain);
    this.put(entry.key,{...entry,issues:current,error:entry.conflict||entry.blocked?entry.error:current.length?'请修正当前页面标出的设置。':''});
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
    if(entry.blocked)throw new Error(entry.error||'这项设置无法读取，修复并重新读取后才可保存。');
    if(entry.invalidEditors.length)throw new Error('当前页还有未完成的 JSON，请修正后保存。');
    if(entry.conflict)throw new SettingsDraftConflictError();
    if(entry.key.domain!=='web'&&!entry.revision)throw new Error('配置版本尚未加载，请重新读取当前页。');
    const payload:Dict={domain:entry.key.domain,scope:entry.key.scope,data:payloadValue(entry.value)};
    if(entry.key.domain!=='web')payload.revision=entry.revision;
    if(entry.key.scope==='project')payload.project_id=entry.key.projectId;
    const ticket=freeze({token:++this.serial,key:clone(entry.key),payload,value:clone(entry.value),
      editVersion:entry.editVersion,revision:entry.revision,editors:clone(entry.editors)});
    this.pending.set(settingsDraftId(entry.key),ticket);
    this.put(entry.key,{...entry,saving:true,error:'',issues:[]});this.publish();
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
    if(incoming)snapshot=mergeSnapshot(snapshot,incoming,revision);
    if(entry.key.domain==='web'&&object(response.preferences))snapshot.preferences=clone(response.preferences);
    snapshot=sanitizeSnapshot(snapshot);
    const acknowledgedStatus=sourceStatus(snapshot,entry.key);
    const acknowledged=(incoming||entry.key.domain==='web'&&object(response.preferences))&&!acknowledgedStatus.blocked
      ?domainValue(snapshot,entry.key):clone(ticket.value);
    const value=rebase(ticket.value,entry.value,acknowledged);
    const editors=Object.fromEntries(Object.entries(entry.editors).filter(([name,draft])=>!equal(draft,ticket.editors[name])));
    // 自己已确认的保存只推进同来源版本；项目组合版本不能套到全局，反之亦然。
    if(incoming||entry.key.domain==='web'){
      this.sessions.set(contextId(entry.key.projectId),freeze({...(entry.key.projectId?{projectId:entry.key.projectId}:{}),snapshot,revision}));
      for(const other of this.entries.values()){
        if(settingsDraftId(other.key)===id||contextId(other.key.projectId)!==contextId(entry.key.projectId))continue;
        const status=sourceStatus(snapshot,other.key);
        if(status.blocked){this.put(other.key,{...other,...status,latestRevision:revision});continue;}
        if(other.dirty||other.saving){
          const eligible=!other.conflict&&other.revision===ticket.revision;
          const issues=mergeSourceIssues(other.blocked?[]:other.issues,status.issues,domainValue(snapshot,other.key),other.value);
          this.put(other.key,{...other,blocked:false,issues,latestRevision:revision,...(eligible?{revision}:{}),conflict:other.conflict,error:issues.length?status.error||other.error:other.blocked?'':other.error});
        }else{
          const next=domainValue(snapshot,other.key);
          this.put(other.key,{...other,value:clone(next),baseline:clone(next),revision,latestRevision:revision,...status,conflict:false});
        }
      }
    }
    this.put(entry.key,{...entry,value,editors,baseline:clone(acknowledged),dirty:!equal(value,acknowledged),
      saving:false,error:acknowledgedStatus.error,issues:acknowledgedStatus.issues,blocked:acknowledgedStatus.blocked,conflict:false,revision,latestRevision:revision,lastSave:clone(response)});
    this.publish();return true;
  }

  failed(ticket:SettingsSaveTicket,error:unknown):boolean {
    const id=settingsDraftId(ticket.key),entry=this.entries.get(id);
    if(!entry||this.pending.get(id)?.token!==ticket.token)return false;
    this.pending.delete(id);
    const conflict=entry.conflict||!!error&&typeof error==='object'&&'status' in error&&error.status===409;
    const returned=errorIssues(error).filter(issue=>issue.domain===entry.key.domain);
    const issues=returned.filter(issue=>equal(valueAtValidationPath(ticket.value,issue.path),valueAtValidationPath(entry.value,issue.path)));
    // 校验针对提交快照；保存期间已修正的字段不能再被迟到错误标红。
    const currentVersion=entry.editVersion===ticket.editVersion;
    const message=conflict?CONFLICT:issues.length?errorText(error):currentVersion&&!returned.length?errorText(error):'';
    this.put(entry.key,{...entry,saving:false,error:message,issues,conflict});this.publish();return true;
  }

  reload(key:SettingsDraftKey,options:{confirmed?:boolean}={}):void {
    const entry=this.get(key);if(!entry)throw new Error('请先读取这项设置。');
    if(entry.saving)throw new Error('当前页正在保存，请等待完成后重新读取。');
    if((entry.dirty||entry.conflict)&&!options.confirmed)throw new Error('重新读取会丢弃当前页草稿，请先确认。');
    const fresh=this.fresh(entry.key);if(!fresh)throw new Error('请先读取最新配置。');
    if(fresh.blocked)throw new Error(fresh.error);
    this.put(entry.key,{...fresh,editVersion:entry.editVersion+1});this.publish();
  }
}

// 放在 App 的 store 实例中保存；设置页卸载不会销毁草稿，也不会把密钥写到浏览器存储。
export function useSettingsDrafts(store:SettingsDraftStore):SettingsDraftStore {
  useSyncExternalStore(store.subscribe,store.getSnapshot,store.getSnapshot);
  return store;
}
