import type {Dict} from './types';
import {Select} from './Select';
import {Advanced,Field,JsonEditor,Numeric} from './SettingsFields';
import type {SettingsEditorDraft} from './settingsDrafts';

export function UiFields({value,onChange}:{value:Dict;onChange:(value:Dict)=>void}){
  const set=(name:string,item:unknown)=>onChange({...value,[name]:item});
  return <>
    <Field label="显示时间戳" path="show_timestamps"><input type="checkbox" checked={!!value.show_timestamps} onChange={event=>set('show_timestamps',event.target.checked)}/></Field>
    <Field label="显示思考状态" path="show_thinking_status" note="只改变轨迹显示，推理强度由对话选择"><input type="checkbox" checked={value.show_thinking_status!==false} onChange={event=>set('show_thinking_status',event.target.checked)}/></Field>
    <Field label="忙时默认输入操作" path="busy_enter_action"><Select value={value.busy_enter_action||'follow_up'} onChange={event=>set('busy_enter_action',event.target.value)}><option value="follow_up">加入后续任务</option><option value="steer">立即补充指令</option><option value="draft">保留草稿</option></Select></Field>
    <Advanced title="TUI 外观" note="终端界面独立主题"><Field label="TUI 主题" path="theme" note="WebUI 主题在“外观”中设置"><Select value={value.theme||'dark'} onChange={event=>set('theme',event.target.value)}><option value="light">浅色</option><option value="dark">深色</option></Select></Field></Advanced>
  </>;
}

const RUNTIME_LABELS:Record<string,string>={tool_loop_limit:'工具循环上限',unknown_tool_streak_limit:'连续未知工具上限',output_continuation_limit:'输出续写上限'};
export function RuntimeFields({value,onChange}:{value:Dict;onChange:(value:Dict)=>void}){
  const set=(name:string,item:unknown)=>onChange({...value,[name]:item});
  return <>
    <Field label="默认工作阶段" path="work_phase"><Select value={value.work_phase||'execute'} onChange={event=>set('work_phase',event.target.value)}><option value="discuss">讨论</option><option value="plan">计划</option><option value="execute">执行</option></Select></Field>
    <Field label="默认访问范围" path="execution_access" note="讨论与计划阶段始终只读"><Select value={value.execution_access||'project'} onChange={event=>set('execution_access',event.target.value)}><option value="project">项目访问</option><option value="full">完全访问</option></Select></Field>
    <Advanced title="循环与续写限制"><div className="field-grid numeric-settings">{Object.entries(RUNTIME_LABELS).map(([name,label])=><Field label={label} path={name} key={name}><Numeric min={1} value={value[name]} onChange={item=>set(name,item)}/></Field>)}</div></Advanced>
    <Advanced title="实验能力"><Field label="实验性 MCP 工具追加" path="experimental_mcp_tool_append"><input type="checkbox" checked={!!value.experimental_mcp_tool_append} onChange={event=>set('experimental_mcp_tool_append',event.target.checked)}/></Field></Advanced>
  </>;
}

const LIMIT_LABELS:Record<string,string>={max_concurrency:'最大并发调用',max_processes:'最大进程总数',max_processes_per_session:'每会话进程上限',output_limit_bytes:'输出存储限制（bytes）',max_read_chars:'单次读取字符上限',stop_grace_seconds:'停止宽限（秒）',drain_timeout_seconds:'输出收尾超时（秒）'};
export function ExecutionFields({value,onChange,editor,onEditor}:{value:Dict;onChange:(value:Dict)=>void;editor?:SettingsEditorDraft;onEditor?:(value:SettingsEditorDraft)=>void}){
  const limit=(name:string,item:unknown)=>onChange({...value,limits:{...value.limits,[name]:item}});
  return <>
    <div className="field-grid numeric-settings">{Object.entries(LIMIT_LABELS).filter(([name])=>['max_concurrency','max_processes'].includes(name)).map(([name,label])=><Field key={name} label={label} path={['limits',name]}><Numeric min={1} value={value.limits?.[name]} onChange={item=>limit(name,item)}/></Field>)}</div>
    <Advanced title="会话资源、输出与超时"><div className="field-grid numeric-settings">{Object.entries(LIMIT_LABELS).filter(([name])=>!['max_concurrency','max_processes'].includes(name)).map(([name,label])=><Field key={name} label={label} path={['limits',name]}><Numeric min={0} value={value.limits?.[name]} onChange={item=>limit(name,item)}/></Field>)}</div></Advanced>
    <Advanced title="命令资源约定" note="完整结构编辑"><JsonEditor label="命令资源配置" path="command_profiles" value={value.command_profiles||[]} onChange={command_profiles=>onChange({...value,command_profiles})} draft={editor} onDraft={onEditor} note="命令资源与就绪条件，修改时保留完整结构。"/></Advanced>
  </>;
}
