import type {Dict} from './types';
import type {ValidationIssue} from './settingsValidation';

type Path=(string|number)[];
const hasText=(value:unknown):value is string=>typeof value==='string'&&!!value.trim();
export const entityText=(value:unknown,fallback='')=>typeof value==='string'?value:typeof value==='number'&&Number.isFinite(value)?String(value):fallback;
export const isValidEntityId=(value:string)=>/^[\p{L}\p{N}_-]+$/u.test(value);
export const isValidMcpName=(value:string)=>/^[A-Za-z0-9_-]+$/.test(value);
export function generateEntityId(source:string,existing:string[],fallback='entry'){
  const base=source.trim().replace(/[^\p{L}\p{N}_-]+/gu,'-').replace(/^-+|-+$/g,'').slice(0,90)||fallback;
  const used=new Set(existing);let id=base,index=2;
  while(used.has(id))id=base+'-'+index++;
  return id;
}
export function isHttpUrl(value:unknown,variables=false,allowQuery=false){
  if(!hasText(value))return false;
  const text=value.trim();
  // 浏览器无法取得服务端环境变量；模板由服务端展开后完成最终校验。
  if(variables&&/\$\{[^}]+\}|\$[A-Za-z_]\w*/.test(text))return true;
  if(/\s/.test(text))return false;
  try{const parsed=new URL(text);return ['http:','https:'].includes(parsed.protocol)&&!!parsed.hostname&&!parsed.username&&!parsed.password&&(allowQuery||!parsed.search&&!parsed.hash);}catch{return false;}
}
const issue=(domain:string,path:Path,field:string,message:string):ValidationIssue=>({domain,path:[...path,field],message});
function numericIssues(value:Dict,fields:string[],path:Path,domain:string,integer=false){
  return fields.filter(field=>value[field]!=null&&(typeof value[field]!=='number'||!Number.isFinite(value[field])||value[field]<=0||integer&&!Number.isInteger(value[field])))
    .map(field=>issue(domain,path,field,integer?'请填写大于 0 的整数。':'请填写大于 0 的有限数值。'));
}
export function validateProviderConnection(value:Dict,path:Path=[],domain='models',creating=false):ValidationIssue[]{
  const issues:ValidationIssue[]=[];
  if(!hasText(value.name))issues.push(issue(domain,path,'name','请填写供应商名称。'));
  if(!['openai','claude'].includes(value.protocol))issues.push(issue(domain,path,'protocol','请选择 OpenAI 兼容或 Anthropic 兼容协议。'));
  if(!isHttpUrl(value.base_url,true))issues.push(issue(domain,path,'base_url','请填写完整的 HTTP(S) Base URL，不包含账号、查询参数或片段。'));
  if(!hasText(value.api_key)&&(creating||!value.api_key_configured||value.api_key_clear))issues.push(issue(domain,path,'api_key','请填写 API Key。'));
  return issues;
}
export function validateProvider(value:Dict,path:Path=[],domain='models',creating=false):ValidationIssue[]{
  const issues=validateProviderConnection(value,path,domain,creating);
  issues.push(...numericIssues(value,['timeout_seconds'],path,domain));
  if(value.timeout_seconds===null)issues.push(issue(domain,path,'timeout_seconds','请填写大于 0 的有限数值。'));
  if(value.api_mode!==undefined&&!['auto','chat_completions','chat_completions_legacy','responses'].includes(value.api_mode))issues.push(issue(domain,path,'api_mode','请选择支持的 OpenAI 接口形式。'));
  return issues;
}
export function validateModel(value:Dict,path:Path=[],domain='models'):ValidationIssue[]{
  const issues:ValidationIssue[]=[];
  if(!hasText(value.model_name))issues.push(issue(domain,path,'model_name','请填写发送给 API 的实际模型名称。'));
  if(value.display_name!=null&&typeof value.display_name!=='string')issues.push(issue(domain,path,'display_name','显示名称必须是文本。'));
  if(value.protocol!=null&&!['openai','claude'].includes(value.protocol))issues.push(issue(domain,path,'protocol','请选择 OpenAI 兼容、Anthropic 兼容或继承供应商。'));
  if(value.base_url!=null&&value.base_url!==''&&!isHttpUrl(value.base_url,true))issues.push(issue(domain,path,'base_url','请填写完整的 HTTP(S) Base URL，或留空继承供应商。'));
  issues.push(...numericIssues(value,['timeout_seconds'],path,domain),...numericIssues(value,['context_window','max_output_tokens'],path,domain,true));
  if(value.api_mode!=null&&!['auto','chat_completions','chat_completions_legacy','responses'].includes(value.api_mode))issues.push(issue(domain,path,'api_mode','请选择支持的 OpenAI 接口形式，或继承供应商。'));
  return issues;
}
export function validateMcp(value:Dict,path:Path=[],domain='mcp'):ValidationIssue[]{
  const issues:ValidationIssue[]=[];
  if(!['stdio','http'].includes(value.type))issues.push(issue(domain,path,'type','请选择 stdio 或 HTTP 传输类型。'));
  if(value.type==='stdio'&&!hasText(value.command))issues.push(issue(domain,path,'command','请填写 MCP 启动命令。'));
  if(value.type==='http'&&!isHttpUrl(value.url,false,true))issues.push(issue(domain,path,'url','请填写完整的 HTTP(S) 服务 URL，不包含账号。'));
  issues.push(...numericIssues(value,['startup_timeout_seconds','tool_timeout_seconds','close_timeout_seconds'],path,domain));
  if(value.args!=null&&(!Array.isArray(value.args)||value.args.some((item:unknown)=>typeof item!=='string')))issues.push(issue(domain,path,'args','命令参数必须是文本数组。'));
  for(const field of ['env','headers'])if(value[field]!=null&&(!value[field]||typeof value[field]!=='object'||Array.isArray(value[field])||Object.values(value[field]).some(item=>typeof item!=='string')))issues.push(issue(domain,path,field,'请填写由文本字段和值组成的映射。'));
  return issues;
}
