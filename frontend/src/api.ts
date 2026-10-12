import type { Dict } from './types';
export class ApiError extends Error { status:number; data:Dict; constructor(message:string,status:number,data:Dict){super(message);this.status=status;this.data=data;} }
export async function api<T=Dict>(path:string, options:RequestInit = {}):Promise<T> {
  let response:Response;
  try {response=await fetch(path,{cache:'no-store',...options,headers:{'Content-Type':'application/json',...options.headers}});} catch {throw new Error('无法连接本地服务，请确认后端正在运行。');}
  let data:Dict={};
  const text=await response.text();
  try {data=text?JSON.parse(text):{};} catch {throw new ApiError(`服务返回了无法读取的响应（${response.status}）。`,response.status,{});}
  if(!response.ok){const detail=data.detail||data.error||data.message;throw new ApiError(typeof detail==='string'?detail:detail?JSON.stringify(detail):`请求失败（${response.status}）。`,response.status,data);}
  return data as T;
}
export const post=<T=Dict>(path:string,data:Dict={})=>api<T>(path,{method:'POST',body:JSON.stringify(data)});
export const patch=<T=Dict>(path:string,data:Dict={})=>api<T>(path,{method:'PATCH',body:JSON.stringify(data)});
export const remove=(path:string)=>api(path,{method:'DELETE'});
export function readLocal<T>(key:string,fallback:T):T {try{const value=localStorage.getItem(`lancher-webui:${key}`);return value?JSON.parse(value):fallback;}catch{return fallback;}}
export function writeLocal(key:string,value:unknown){try{localStorage.setItem(`lancher-webui:${key}`,JSON.stringify(value));}catch{/* 无存储权限时保留内存内状态。 */}}
export const isBusy=(status?:string)=>['queued','running','waiting_permission','stopping','busy'].includes(status||'');
export const statusLabel=(status?:string)=>({idle:'准备就绪',queued:'排队中',running:'正在工作',waiting_permission:'等待审批',stopping:'正在收尾',completed:'已完成',failed:'失败',cancelled:'已停止',busy:'会话已被占用',interrupted:'已中断'}[status||'']||status||'准备就绪');
export const phaseLabel=(phase?:string)=>({discuss:'讨论',plan:'计划',execute:'执行'}[phase||'']||phase||'执行');
export const accessLabel=(access?:string)=>({read_only:'只读',project:'项目访问',full:'完全访问'}[access||'']||access||'项目访问');
export const num=(n:unknown)=>typeof n==='number'?n.toLocaleString('zh-CN'):'—';
export const pretty=(value:unknown)=>typeof value==='string'?value:JSON.stringify(value??{},null,2);
