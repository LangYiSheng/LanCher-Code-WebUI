import {useEffect,useRef,useState} from 'react';
import type {Dict} from './types';
import {Modal,useDialogs} from './Dialogs';
import {Select} from './Select';
import {Icon} from './Icon';
import {Advanced,Field,Numeric} from './SettingsFields';
import {ValidationProvider,ValidationScope,focusValidationIssue,type ValidationIssue} from './settingsValidation';
import {entityText,isValidMcpName,validateMcp} from './entityValidation';
import './EntityForms.css';

export function SecretMap({label,value,onChange,removed,path}:{label:string;value:Dict;onChange:(value:Dict,removed:string[])=>void;removed:string[];path:string}){
  const {prompt}=useDialogs();
  return <div className="secret-map"><div className="section-heading"><h3>{label}</h3><button type="button" className="text-button" onClick={()=>void prompt({title:'新增'+label+'字段',label:'字段名称',confirmLabel:'添加',maxLength:200,validate:key=>Object.hasOwn(value,key)?'这个字段已存在。':/\s/.test(key)?'字段名称不能包含空白。':undefined,onSubmit:key=>onChange({...value,[key]:''},removed.filter(item=>item!==key))})}>新增字段</button></div>
    {Object.entries(value||{}).map(([key,item])=><Field path={[path,key]} label={key} key={key}><input aria-label={label+' '+key} type="password" autoComplete="new-password" value={item??''} placeholder="留空保留已配置值" onChange={event=>onChange({...value,[key]:event.target.value},removed.filter(item=>item!==key))}/><div className="field-subactions"><button type="button" className="text-button danger-text" title="删除这个字段" aria-label={'删除'+label+' '+key} onClick={()=>{const next={...value};delete next[key];onChange(next,[...new Set([...removed,key])]);}}>删除字段</button></div></Field>)}
    <p className="small-note">已配置的值不会显示。留空保留原值；删除会移除整个字段。</p>
  </div>;
}
function McpConnectionFields({value,onChange,creating=false}:{value:Dict;onChange:(value:Dict)=>void;creating?:boolean}){
  const set=(key:string,item:any)=>onChange({...value,[key]:item});
  return <div className="connection-settings">
    <Field path="type" label="传输类型" note="本地进程使用 stdio，远程服务使用 HTTP" required><Select value={entityText(value.type)} onChange={event=>set('type',event.target.value)}><option value="" disabled>请选择传输类型</option><option value="stdio">标准输入输出（stdio）</option><option value="http">HTTP</option></Select></Field>
    {!creating&&<Field path="enabled" label="启用"><input type="checkbox" checked={value.enabled!==false} onChange={event=>set('enabled',event.target.checked)}/></Field>}
    {value.type==='http'?<Field path="url" label="服务 URL" note="填写 MCP HTTP 端点的完整地址" required><input value={entityText(value.url)} onChange={event=>set('url',event.target.value)} placeholder="例如 https://mcp.example.com/mcp" inputMode="url" spellCheck={false}/></Field>:value.type==='stdio'?<>
      <Field path="command" label="启动命令" note="只填可执行程序，命令参数在下方单独填写" required><input value={entityText(value.command)} onChange={event=>set('command',event.target.value)} placeholder="例如 npx、uvx 或 python" spellCheck={false}/></Field>
      <Field path="args" label="命令参数" note="每行一个参数"><textarea value={(Array.isArray(value.args)?value.args:[]).map((item:unknown)=>entityText(item)).join('\n')} onChange={event=>set('args',event.target.value.split('\n').filter(Boolean))} placeholder={'例如 -y\n@modelcontextprotocol/server-example'}/></Field>
    </>:null}
  </div>;
}
function McpAdvancedFields({value,onChange}:{value:Dict;onChange:(value:Dict)=>void}){
  return <Advanced title="MCP 高级设置" note={value.type==='http'?'请求头与超时':'环境变量与超时'}>
    <div className="field-grid numeric-settings"><Field path="startup_timeout_seconds" label="启动超时（秒）" note="留空使用默认值"><Numeric min={1} value={value.startup_timeout_seconds} onChange={item=>onChange({...value,startup_timeout_seconds:item})}/></Field><Field path="tool_timeout_seconds" label="工具超时（秒）" note="留空使用默认值"><Numeric min={1} value={value.tool_timeout_seconds} onChange={item=>onChange({...value,tool_timeout_seconds:item})}/></Field><Field path="close_timeout_seconds" label="关闭超时（秒）" note="留空使用默认值"><Numeric min={1} value={value.close_timeout_seconds} onChange={item=>onChange({...value,close_timeout_seconds:item})}/></Field></div>
    {value.type==='http'?<SecretMap path="headers" label="请求头" value={value.headers||{}} onChange={(headers,headers_remove)=>onChange({...value,headers,headers_remove,headers_clear:(value.headers_clear||[]).filter((name:string)=>!headers[name])})} removed={value.headers_remove||[]}/>:value.type==='stdio'?<SecretMap path="env" label="环境变量" value={value.env||{}} onChange={(env,env_remove)=>onChange({...value,env,env_remove,env_clear:(value.env_clear||[]).filter((name:string)=>!env[name])})} removed={value.env_remove||[]}/>:null}
  </Advanced>;
}
export function McpCreateDialog({existing,onClose,onCreate}:{existing:Dict;onClose:()=>void;onCreate:(name:string,value:Dict)=>void}){
  const [name,setName]=useState(''),[value,setValue]=useState<Dict>({type:'',enabled:true,command:'',url:'',args:[],env:{},headers:{},tool_timeout_seconds:60}),[issues,setIssues]=useState<ValidationIssue[]>([]);const form=useRef<HTMLFormElement>(null);
  useEffect(()=>{const frame=requestAnimationFrame(()=>form.current?.querySelector<HTMLInputElement>('input')?.focus());return()=>cancelAnimationFrame(frame);},[]);
  function edit(next:Dict){setValue(next);setIssues(items=>items.filter(item=>item.path[0]==='name'||Object.is(value[item.path[0]],next[item.path[0]])&&!(value.type!==next.type&&['command','url','args','headers','env'].includes(String(item.path[0])))));}
  function submit(){
    const id=name.trim(),next=validateMcp(value);
    if(!id)next.unshift({domain:'mcp',path:['name'],message:'请填写 MCP 服务名称。'});
    else if(!isValidMcpName(id))next.unshift({domain:'mcp',path:['name'],message:'服务名称只能包含字母、数字、短横线和下划线。'});
    else if(Object.hasOwn(existing,id))next.unshift({domain:'mcp',path:['name'],message:'这个 MCP 服务名称已存在。'});
    setIssues(next);if(next.length){requestAnimationFrame(()=>focusValidationIssue(next[0],form.current||undefined));return;}
    const common={type:value.type,enabled:true,startup_timeout_seconds:value.startup_timeout_seconds,tool_timeout_seconds:value.tool_timeout_seconds,close_timeout_seconds:value.close_timeout_seconds};
    onCreate(id,value.type==='http'?{...common,url:value.url.trim(),headers:value.headers}:{...common,command:value.command.trim(),args:value.args,env:value.env});
  }
  return <Modal title="新增 MCP 服务" subtitle="填写与传输类型对应的连接信息，添加后保存设置生效。" onClose={onClose} className="entity-create-modal settings-redesign">
    <form ref={form} noValidate onSubmit={event=>{event.preventDefault();submit();}}><ValidationProvider domain="mcp" issues={issues}>
      <div className="connection-settings"><Field path="name" label="服务名称" note="使用字母、数字、短横线或下划线，例如 filesystem" required><input autoFocus value={name} maxLength={100} onChange={event=>{setName(event.target.value);setIssues(items=>items.filter(item=>item.path[0]!=='name'));}} placeholder="例如 filesystem"/></Field></div>
      <McpConnectionFields creating value={value} onChange={edit}/>
      {value.type&&<McpAdvancedFields value={value} onChange={edit}/>}
      <div className="modal-footer"><button type="button" className="secondary-button" onClick={onClose}>取消</button><button type="submit" className="primary-button"><Icon name="plus" size={15}/>添加服务</button></div>
    </ValidationProvider></form>
  </Modal>;
}
export function McpEditor({value,onChange,issues=[],focusedIssue}:{value:Dict;onChange:(value:Dict)=>void;issues?:ValidationIssue[];focusedIssue?:ValidationIssue|null}){
  const {confirm}=useDialogs();const [creating,setCreating]=useState(false),[selected,setSelected]=useState(Object.keys(value||{})[0]||'');
  const server=value?.[selected],update=(next:Dict)=>onChange({...value,[selected]:next});
  useEffect(()=>{if(!value?.[selected])setSelected(Object.keys(value||{})[0]||'');},[value,selected]);
  useEffect(()=>{const issue=focusedIssue||issues[0],id=issue?.path[0];if(typeof id==='string'&&value?.[id])setSelected(id);},[focusedIssue,issues]);
  return <>
    <div className="editor-heading"><h3>MCP 服务</h3><button className="secondary-button" onClick={()=>setCreating(true)}><Icon name="plus" size={14}/>新增服务</button></div>
    <div className="model-selector"><Select aria-label="选择 MCP 服务" value={selected} onChange={event=>setSelected(event.target.value)}><option value="">选择服务…</option>{Object.keys(value||{}).map(name=><option key={name}>{name}</option>)}</Select>{server&&<button className="danger-text" onClick={async()=>{if(!await confirm({title:'删除 MCP 服务',message:'将从待保存配置中移除 '+selected+'。保存设置后生效。',confirmLabel:'移除服务',danger:true}))return;const next={...value};delete next[selected];onChange(next);}}>删除服务</button>}</div>
    {server?<ValidationScope path={[selected]}><p className="mcp-service-description">{server.type==='http'?'HTTP · '+(entityText(server.url)||'尚未填写服务 URL'):'stdio · '+(entityText(server.command)||'尚未填写启动命令')}</p><McpConnectionFields value={server} onChange={update}/><McpAdvancedFields value={server} onChange={update}/></ValidationScope>:<div className="panel-empty">添加服务时，请填写传输类型和对应的启动命令或 HTTP 地址。</div>}
    {creating&&<McpCreateDialog existing={value||{}} onClose={()=>setCreating(false)} onCreate={(name,server)=>{onChange({...value,[name]:server});setSelected(name);setCreating(false);}}/>}
  </>;
}
