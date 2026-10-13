import {createContext,createElement,useContext,type ReactNode} from 'react';
import {isValidEntityId,isValidMcpName,validateModel,validateProvider,validateMcp} from './entityValidation.ts';
import type {Dict} from './types';

export type ValidationPath=(string|number)[];
export type ValidationIssue={domain:string;path:ValidationPath;message:string};
export type ValidationPathInput=string|number|ValidationPath;

export const validationPath=(path?:ValidationPathInput):ValidationPath=>path===undefined?[]:Array.isArray(path)?[...path]:[path];
export const validationPathKey=(domain:string,path:ValidationPath):string=>JSON.stringify([domain,...path]);
export function normalizeValidationIssues(value:unknown):ValidationIssue[]{
  if(!Array.isArray(value))return [];
  return value.flatMap(item=>item&&typeof item==='object'&&typeof item.domain==='string'&&typeof item.message==='string'
    &&Array.isArray(item.path)&&item.path.every((part:unknown)=>typeof part==='string'||typeof part==='number'&&Number.isFinite(part))
    ?[{domain:item.domain,path:[...item.path],message:item.message}]:[]);
}
export function valueAtValidationPath(value:unknown,path:ValidationPath):unknown {
  let current:any=value;
  for(const part of path){if(!current||typeof current!=='object'||!Object.hasOwn(current,part))return undefined;current=current[part];}
  return current;
}
export const isValidationPathPrefix=(prefix:ValidationPath,path:ValidationPath):boolean=>prefix.length<=path.length&&prefix.every((part,index)=>part===path[index]);

const isObject=(value:unknown):value is Dict=>!!value&&typeof value==='object'&&!Array.isArray(value);
export function validateModelsSettings(value:unknown):ValidationIssue[]{
  const issue=(path:ValidationPath,message:string):ValidationIssue=>({domain:'models',path,message});
  if(!isObject(value)||!isObject(value.providers))return [issue(['providers'],'供应商目录必须是对象。')];
  const issues:ValidationIssue[]=[];
  if(!Object.keys(value.providers).length)issues.push(issue(['providers'],'请添加至少一个供应商及模型。'));
  let count=0;
  for(const [providerId,provider] of Object.entries(value.providers)){
    const path=['providers',providerId];
    if(!isValidEntityId(providerId))issues.push(issue(path,'供应商标识只能包含中文、字母、数字、下划线和短横线。'));
    if(!isObject(provider)){issues.push(issue(path,'供应商配置必须是对象。'));continue;}
    issues.push(...validateProvider(provider,path));
    if(!isObject(provider.models)){issues.push(issue([...path,'models'],'模型目录必须是对象。'));continue;}
    for(const [modelId,model] of Object.entries(provider.models)){
      const modelPath=[...path,'models',modelId];count++;
      if(!isValidEntityId(modelId))issues.push(issue(modelPath,'模型标识只能包含中文、字母、数字、下划线和短横线。'));
      if(!isObject(model)){issues.push(issue(modelPath,'模型配置必须是对象。'));continue;}
      issues.push(...validateModel(model,modelPath));
    }
  }
  if(!count&&Object.keys(value.providers).length)issues.push(issue(['default_model'],'请添加至少一个模型，并将它设为默认模型。'));
  const selected=typeof value.default_model==='string'?value.default_model.split('/'):[];
  if(selected.length!==2||!selected[0]||!selected[1]||!Object.hasOwn(value.providers,selected[0])||!isObject(value.providers[selected[0]]?.models)||!Object.hasOwn(value.providers[selected[0]].models,selected[1])){
    if(count||!issues.some(item=>item.path[0]==='default_model'))issues.push(issue(['default_model'],'请选择目录中存在的默认模型。'));
  }
  return issues;
}
export function validateMcpSettings(value:unknown):ValidationIssue[]{
  const issue=(path:ValidationPath,message:string):ValidationIssue=>({domain:'mcp',path,message});
  if(!isObject(value))return [issue([],'MCP 服务目录必须是对象。')];
  return Object.entries(value).flatMap(([name,server])=>[
    ...(!isValidMcpName(name)?[issue([name],'MCP 服务名称只能包含英文字母、数字、下划线和短横线。')]:[]),
    ...(isObject(server)?validateMcp(server,[name]):[issue([name],'MCP 服务配置必须是对象。')]),
  ]);
}
const FIELD_LABELS:Record<string,string>={
  providers:'供应商目录',models:'模型目录',default_model:'默认模型',name:'名称',protocol:'调用协议',api_mode:'接口形式',base_url:'Base URL',api_key:'API Key',model_name:'API 模型名称',display_name:'显示名称',
  timeout_seconds:'请求超时',context_window:'上下文窗口',max_output_tokens:'总输出额度',type:'传输类型',enabled:'启用',command:'启动命令',args:'命令参数',url:'服务 URL',env:'环境变量',headers:'请求头',
  startup_timeout_seconds:'启动超时',tool_timeout_seconds:'工具超时',close_timeout_seconds:'关闭超时',match:'匹配目标',match_kind:'匹配方式',command_cwd:'命令目录',command_shell:'命令 Shell',
  show_timestamps:'显示时间戳',show_thinking_status:'显示思考状态',theme:'主题',busy_enter_action:'忙时输入操作',work_phase:'工作阶段',execution_access:'访问范围',
  tool_loop_limit:'工具循环上限',unknown_tool_streak_limit:'连续未知工具上限',output_continuation_limit:'输出续写上限',experimental_mcp_tool_append:'动态添加 MCP 工具',
  limits:'资源限制',command_profiles:'命令资源配置',max_concurrency:'最大并发调用',max_processes:'最大进程总数',max_processes_per_session:'每会话进程上限',output_limit_bytes:'输出存储限制',max_read_chars:'读取字符上限',stop_grace_seconds:'停止宽限',drain_timeout_seconds:'输出收尾超时',
};
const DOMAIN_LABELS:Record<string,string>={models:'模型与供应商',mcp:'MCP 服务',rules:'权限规则',ui:'输入与显示',runtime:'Agent 行为',execution:'执行与进程',web:'外观'};
export function validationIssueLabel(issue:ValidationIssue):string {
  const path=[...issue.path],parts:string[]=[];
  if(issue.domain==='models'&&path[0]==='providers'&&path.length>1){
    parts.push('供应商 '+path[1]);path.splice(0,2);
    if(String(path[0])==='models'&&path.length>1){parts.push('模型 '+path[1]);path.splice(0,2);}
  }else if(issue.domain==='mcp'&&path.length){parts.push('MCP '+path.shift());}
  else parts.push(DOMAIN_LABELS[issue.domain]||'设置');
  parts.push(...path.map(part=>typeof part==='number'?'第 '+(part+1)+' 项':FIELD_LABELS[part]||part));
  return parts.join(' · ');
}

type ValidationContextValue={domain:string;path:ValidationPath;issues:ValidationIssue[]};
const Context=createContext<ValidationContextValue>({domain:'',path:[],issues:[]});
export function ValidationProvider({domain,issues,children}:{domain:string;issues:ValidationIssue[];children:ReactNode}){
  return createElement(Context.Provider,{value:{domain,path:[],issues}},children);
}
export function ValidationScope({path,children}:{path:ValidationPathInput;children:ReactNode}){
  const parent=useContext(Context);
  return createElement(Context.Provider,{value:{...parent,path:[...parent.path,...validationPath(path)]}},children);
}
export function useFieldValidation(path?:ValidationPathInput){
  const context=useContext(Context),fullPath=[...context.path,...validationPath(path)];
  const issues=context.issues.filter(issue=>issue.domain===context.domain&&isValidationPathPrefix(fullPath,issue.path));
  return {...context,path:fullPath,issues};
}

// 分类与实体切换需要先完成渲染，随后再展开高级区并定位字段。
export async function focusValidationIssue(issue:ValidationIssue,root?:HTMLElement):Promise<boolean>{
  if(typeof document==='undefined')return false;
  const schedule=(callback:()=>void)=>typeof requestAnimationFrame==='function'?requestAnimationFrame(callback):setTimeout(callback,0);
  return new Promise(resolve=>{
    let attempts=0;
    const locate=()=>{
      const container=root||document;
      const fields=Array.from(container.querySelectorAll<HTMLElement>('[data-setting-path]'));
      if(root?.hasAttribute('data-setting-path'))fields.unshift(root);
      let field:HTMLElement|undefined;
      for(let length=issue.path.length;length>=0&&!field;length--){const target=validationPathKey(issue.domain,issue.path.slice(0,length));field=fields.find(item=>item.dataset.settingPath===target);}
      if(!field){if(++attempts<3){schedule(locate);return;}resolve(false);return;}
      for(let ancestor:HTMLElement|null=field;ancestor;ancestor=ancestor.parentElement){if(ancestor.tagName==='DETAILS')(ancestor as HTMLDetailsElement).open=true;}
      const control=field.querySelector<HTMLElement>('input:not([type="hidden"]):not(:disabled),textarea:not(:disabled),select:not(:disabled),button:not(:disabled),[tabindex]')||field;
      if(control===field&&!field.hasAttribute('tabindex'))field.tabIndex=-1;
      field.scrollIntoView?.({block:'center',behavior:'auto'});control.focus({preventScroll:true});resolve(true);
    };
    schedule(locate);
  });
}

export function ValidationSummary({issues,onSelect}:{issues:ValidationIssue[];onSelect?:(issue:ValidationIssue)=>void}){
  if(!issues.length)return null;
  return createElement('div',{className:'settings-validation-summary',role:'alert'},
    createElement('strong',null,`请修正以下 ${issues.length} 处设置：`),
    createElement('ul',null,...issues.map((issue,index)=>createElement('li',{key:validationPathKey(issue.domain,issue.path)+':'+index},
      createElement('button',{type:'button',className:'text-button','aria-label':'定位错误：'+validationIssueLabel(issue)+'，'+issue.message,onClick:()=>{if(onSelect)onSelect(issue);else void focusValidationIssue(issue);}},validationIssueLabel(issue)+'：'+issue.message)))));
}
