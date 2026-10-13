import {useEffect,useLayoutEffect,useRef,useState,type ReactNode,type PointerEvent as ReactPointerEvent,type KeyboardEvent as ReactKeyboardEvent} from 'react';
import type {ChatDetail,Dict,FileEntry,Project} from './types';
import type {ActionFn} from './ChatView';
import {api,isBusy,num,pretty,readLocal,writeLocal,statusLabel,phaseLabel} from './api';
import {Icon,Spinner,toolIconName} from './Icon';
import {contextSummary,usageSummary,type UsageScope,type TokenField} from './usage';
import {useDialogs} from './Dialogs';
import {ProcessesPanel} from './ProcessesPanel';
import {groupProcesses} from './processPresentation';
import {clampPanelWidth,panelBounds,PANEL_CLOSE_THRESHOLD} from './panelResize';
import {changeLabels,fileEntries,fileListUrl,filePreviewUrl,fileScopeKey,isChangeStatus,fileTree,parentDirectories,restoreInspectorView,inspectorTabTypes,type ChangeStatus,type FileScope,type FileSelection,type FileTreeNode,type InspectorTab} from './inspectorFiles';
export type {InspectorTab} from './inspectorFiles';
function UsagePanel({chat}:{chat:ChatDetail}){
  const [scope,setScope]=useState<UsageScope>('session');const summary=usageSummary(chat.usage,scope),context=contextSummary(chat.context);
  const fields:[TokenField,string][]=[['input_tokens','输入'],['output_tokens','输出'],['cached_input_tokens','缓存读取'],['reasoning_output_tokens','思考输出']];
  return <div className="usage-panel"><header className="panel-heading"><div><h2>用量</h2></div></header>
    <section className="context-overview"><div><span>当前上下文</span><strong>{context.percent===null?'—':context.percent+'%'}<small> 已用</small></strong></div><div className="context-progress" role="progressbar" aria-label="当前上下文占用" aria-valuenow={context.percent===null?undefined:Math.min(100,context.percent)} aria-valuemin={0} aria-valuemax={100} aria-valuetext={context.label}><span style={{width:context.percent===null?'0%':Math.min(100,context.percent)+'%'}}/></div><p>{num(context.tokens)} / {num(context.window)} tokens <span>{context.source}</span></p></section>
    <div className="segmented usage-scopes" role="group" aria-label="用量统计范围">{([['answer','本轮'],['session','会话'],['project','项目'],['server','服务']] as const).map(([key,label])=><button key={key} aria-pressed={scope===key} className={scope===key?'active':''} onClick={()=>setScope(key)}>{label}</button>)}</div>
    <div className="usage-total"><div><span>累计 token</span><strong>{num(summary.total)}</strong><small>{summary.totalPartial?'已知小计':'输入 + 输出'}</small></div><div><span>缓存命中率</span><strong>{summary.cacheRatioText}</strong><small>{summary.requestCount===null?'请求数未知':summary.requestCount+' 次请求'}</small></div></div>
    <div className="usage-metrics">{fields.map(([key,label])=>{const value=summary.tokens[key],subtotal=summary.knownSubtotal(key);return <div key={key}><span>{label}</span><strong>{num(value)}</strong><small>{value!==null&&summary.isPartial(key)?'已知小计':subtotal!==null?'已知小计 '+num(subtotal):'tokens'}</small></div>;})}</div>
    <div className="usage-quality"><Icon name="info" size={13}/><span>{summary.quality}{summary.cacheRatioNote?' · '+summary.cacheRatioNote:''}</span></div>
    <div className="inspector-section"><details className="panel-disclosure"><summary>统计详情<Icon name="down" size={13}/></summary><dl className="data-list"><div><dt>缓存创建</dt><dd>{num(summary.tokens.cache_creation_input_tokens)}{summary.isPartial('cache_creation_input_tokens')?'（已知小计）':''}</dd></div><div><dt>不完整上报</dt><dd>{num(summary.incomplete)}</dd></div><div><dt>无效用量请求</dt><dd>{num(summary.invalid)}</dd></div></dl><p className="small-note">缓存计入输入，思考计入输出，不重复累加；未知字段显示 —。{context.snapshot?'上下文来自保存快照，运行后可能变化。':''}</p></details>{chat.context?.compaction&&<details className="panel-disclosure"><summary>压缩记录<Icon name="down" size={13}/></summary><pre className="plain-output">{pretty(chat.context.compaction)}</pre></details>}</div>
  </div>;
}
function QueuePanel({chat,action,notify}:{chat:ChatDetail;action:ActionFn;notify:(text:string)=>void}){
  const {prompt}=useDialogs();
  return <div className="inspector-section"><div className="section-heading"><h3>输入队列 <span>{chat.queue.length}</span></h3><button className="text-button" disabled={(chat.queue_paused||chat.queue.some(x=>x.state==='paused'))&&isBusy(chat.status)} onClick={()=>void action((chat.queue_paused||chat.queue.some(x=>x.state==='paused'))?'queue_resume':'queue_pause')}>{(chat.queue_paused||chat.queue.some(x=>x.state==='paused'))?'恢复队列':'暂停队列'}</button></div>{chat.pending_task&&<div className="queue-card pending-task"><span className="tag">等待恢复的任务</span><p>{chat.pending_task.prompt||chat.pending_task.text||({compact:'压缩上下文',queue:'后续输入队列',turn:'聊天任务'} as Dict)[chat.pending_task.kind]||chat.pending_task.kind}</p><button className="secondary-button" disabled={['queued','running','waiting_permission','stopping'].includes(chat.status)} onClick={()=>void action('queue_resume')}>恢复任务</button></div>}{!chat.queue.length&&!chat.pending_task&&<p className="small-note">暂无排队输入</p>}{chat.queue.map(item=><div className="queue-card" key={item.id}><div><span className="tag">{item.delivery==='steer'?'即时补充':'后续任务'}</span><span className="small-note">{item.state==='paused'?'已暂停':'待处理'}</span></div><p>{item.text}</p><div className="row-actions"><button onClick={async()=>{await prompt({title:'编辑排队输入',label:'任务内容',initialValue:item.text,multiline:true,maxLength:20000,confirmLabel:'保存',validate:text=>text.trim()?undefined:'任务内容不能为空。',onSubmit:async(text)=>{const result=await action('queue_update',{id:item.id,text});if(!result)throw new Error('队列更新未成功，请重试。');}});}}><Icon name="edit" size={13}/>编辑</button><button onClick={()=>void action('queue_convert',{id:item.id,delivery:item.delivery==='steer'?'follow_up':'steer'})}>{item.delivery==='steer'?'改为后续任务':'改为即时补充'}</button><button onClick={()=>void action('queue_remove',{id:item.id}).then(result=>{if(result)notify('已移除队列输入。');})}><Icon name="close" size={13}/>移除</button></div></div>)}</div>;
}
export function Capabilities({chat,action}:{chat:ChatDetail;action:ActionFn}){
  const [pending,setPending]=useState('');const locked=useRef(false),busy=isBusy(chat.status);
  const skills=chat.capabilities.skills,servers=chat.capabilities.mcp;
  async function run(kind:string,name?:string){if(locked.current)return;locked.current=true;setPending(kind+(name||''));try{await action(kind,name?{name}:{});}finally{locked.current=false;setPending('');}}
  const ready=servers.filter(server=>server.state==='ready').length;
  return <><header className="panel-heading"><div><h2>扩展</h2><p>{ready} / {servers.length} 个服务就绪</p></div><Icon name="link" size={18}/></header>{busy&&<p className="panel-hint">运行中暂不可修改扩展</p>}
    <div className="inspector-section"><div className="section-heading"><h3>Skills <span>{skills.length}</span></h3><button className="text-button" disabled={busy||!!pending} onClick={()=>void run('skills_reload')}>{pending==='skills_reload'?<Spinner/>:<Icon name="refresh" size={13}/>}重新扫描</button></div>
      {skills.length?skills.map((skill,i)=><details className="capability capability-disclosure" key={skill.id||skill.name||i}><summary><Icon name="skill" size={15}/><strong>{skill.name||skill.id||'Skill'}</strong><span className={'process-status '+(skill.enabled===false?'muted':'success')}>{skill.enabled===false?'已禁用':skill.loaded?'已加载':'已启用'}</span><Icon name="down" size={12}/></summary><p>{skill.description||skill.path||'暂无说明'}</p><div className="row-actions"><button disabled={!!pending} onClick={()=>void run('skills_show',skill.id||skill.name)}>查看内容</button><button disabled={busy||!!pending} onClick={()=>void run(skill.enabled===false?'skills_enable':'skills_disable',skill.id||skill.name)}>{skill.enabled===false?'启用':'禁用'}</button>{skill.loaded&&<button disabled={busy||!!pending} onClick={()=>void run('skills_unload',skill.id||skill.name)}>卸载上下文</button>}</div></details>):<div className="compact-empty"><Icon name="skill" size={17}/><span>尚未发现技能</span></div>}
    </div><div className="inspector-section"><div className="section-heading"><h3>MCP <span>{servers.length}</span></h3><button className="text-button" disabled={busy||!!pending} onClick={()=>void run('mcp_reload')}>{pending==='mcp_reload'?<Spinner/>:<Icon name="refresh" size={13}/>}重载配置</button></div>
      {servers.length?servers.map((server,i)=><div className="capability" key={server.name||i}><div className="section-heading"><strong><span className={'status-dot '+(server.state==='ready'?'green':'')}/>{server.name||server.id||'MCP'}</strong><span className={'process-status '+(server.state==='ready'?'success':server.last_error?'danger':'muted')}>{({ready:'已连接',connecting:'连接中',failed:'连接失败',disabled:'已禁用',disconnected:'未连接',error:'异常'} as Dict)[server.state]||server.state||'状态未知'}</span></div><p>{typeof(server.registered_tools??server.tool_count)==='number'?(server.registered_tools??server.tool_count)+' 个可用工具':'工具数量未知'}</p>{server.last_error&&<p className="inline-error">{server.last_error}</p>}<div className="row-actions">{server.state==='ready'&&<button disabled={busy||!!pending} onClick={()=>void run('mcp_refresh',server.name)}>刷新工具</button>}<button disabled={busy||!!pending} onClick={()=>void run('mcp_reconnect',server.name)}>重新连接</button></div></div>):<div className="compact-empty"><Icon name="link" size={17}/><span>暂无 MCP 服务</span></div>}
    </div></>;
}

type FileListResponse={files:FileEntry[];scope?:FileScope;truncated?:boolean;change_count?:number;change_summary?:Partial<Record<ChangeStatus,number>>};
type ListState={key:string;data:FileListResponse|null;loading:boolean;error:string};
type PreviewState={key:string;file:Dict|null;loading:boolean;error:string};

function FilePane({scope,project,chat,selection,onChange,filePath,setFilePath,toolResults}:{scope:FileScope;project:Project;chat?:ChatDetail;selection:FileSelection;onChange:(value:Partial<FileSelection>)=>void;filePath:string;setFilePath:(path:string)=>void;toolResults:number}){
  const [refresh,setRefresh]=useState(0),[wrap,setWrap]=useState(false),[copyState,setCopyState]=useState('');
  const [list,setList]=useState<ListState>({key:'',data:null,loading:false,error:''});
  const [preview,setPreview]=useState<PreviewState>({key:'',file:null,loading:false,error:''});
  const listGeneration=useRef(0),previewGeneration=useRef(0);
  const scopeKey=fileScopeKey(scope,project.id,chat?.id);
  const listUrl=fileListUrl(scope,project.id,chat?.id,selection.query);
  const updateKey=JSON.stringify([chat?.id||'',chat?.status||'',toolResults,refresh]);
  const listKey=JSON.stringify([scopeKey,listUrl,updateKey]);
  const currentList=list.key===listKey?list:null;
  const rows=fileEntries(scope,currentList?.data?.files||[]);
  const selectedEntry=rows.find(entry=>entry.path===selection.path);
  const canPreview=!!selection.path&&(scope==='files'||!!currentList?.data&&!!selectedEntry);
  const previewUrl=canPreview?filePreviewUrl(scope,project.id,chat?.id,selection.path):'';
  const previewKey=JSON.stringify([scopeKey,previewUrl,updateKey]);
  const currentPreview=canPreview&&preview.key===previewKey?preview:null;
  const file=currentPreview?.file;
  // 标签决定视图：项目文件始终看源码，对话变更始终对比本对话基线。
  const isDiff=scope==='changes',code=isDiff?file?.diff:file?.content;
  useEffect(()=>setCopyState(''),[selection.path,code]);
  const status=isChangeStatus(file?.change_status)?file.change_status:selectedEntry?.status;
  const changeCount=currentList?.data?.change_count??rows.length;
  const collapsed=new Set(selection.collapsed);

  useEffect(()=>{
    if(scope==='files'&&filePath!==selection.path)
      onChange({path:filePath,collapsed:selection.collapsed.filter(path=>!parentDirectories(filePath).includes(path))});
  },[scope,filePath]);

  useEffect(()=>{
    const controller=new AbortController(),generation=++listGeneration.current;
    setList({key:listKey,data:null,loading:!!listUrl,error:''});
    const timer=setTimeout(()=>{
      if(!listUrl)return;
      void api<FileListResponse>(listUrl,{signal:controller.signal}).then(data=>{
        if(controller.signal.aborted||generation!==listGeneration.current)return;
        if(scope==='changes'&&data.scope!=='changes')throw new Error('变更列表来源不一致，请刷新后重试。');
        setList({key:listKey,data,loading:false,error:''});
      }).catch(err=>{
        if(!controller.signal.aborted&&generation===listGeneration.current)
          setList({key:listKey,data:null,loading:false,error:err instanceof Error?err.message:String(err)});
      });
    },150);
    return()=>{clearTimeout(timer);controller.abort();};
  },[listKey,listUrl,scope]);

  useEffect(()=>{
    if(scope==='changes'&&selection.path&&currentList?.data&&!selectedEntry)onChange({path:''});
  },[scope,selection.path,currentList?.data,selectedEntry]);

  useEffect(()=>{
    const controller=new AbortController(),generation=++previewGeneration.current;
    setPreview({key:previewKey,file:null,loading:!!previewUrl,error:''});
    if(previewUrl)void api(previewUrl,{signal:controller.signal}).then(data=>{
      if(!controller.signal.aborted&&generation===previewGeneration.current)
        setPreview({key:previewKey,file:data,loading:false,error:''});
    }).catch(err=>{
      if(!controller.signal.aborted&&generation===previewGeneration.current)
        setPreview({key:previewKey,file:null,loading:false,error:err instanceof Error?err.message:String(err)});
    });
    return()=>controller.abort();
  },[previewKey,previewUrl]);

  function select(path:string){
    onChange({path,collapsed:selection.collapsed.filter(item=>!parentDirectories(path).includes(item))});
    if(scope==='files')setFilePath(path);
  }
  function treeNodes(nodes:FileTreeNode[],depth=0):ReactNode{
    return nodes.map(node=>node.file?<button role="treeitem" aria-selected={node.path===selection.path}
      className={'file-tree-row '+(node.path===selection.path?'selected':'')} key={node.path} title={node.path}
      style={{paddingLeft:10+depth*14}} onClick={()=>select(node.path)}>
      <Icon name={isDiff&&node.file.status==='deleted'?'delete':'file'} size={14}/><span>{node.name}</span>
      {isDiff&&isChangeStatus(node.file.status)&&<small className={'file-status '+node.file.status}>{changeLabels[node.file.status]}</small>}
    </button>:<div className="tree-directory" key={node.path}>
      <button role="treeitem" aria-expanded={!collapsed.has(node.path)} className="file-tree-row tree-toggle"
        title={node.path} style={{paddingLeft:10+depth*14}} onClick={()=>onChange({collapsed:collapsed.has(node.path)
          ?selection.collapsed.filter(path=>path!==node.path):[...selection.collapsed,node.path]})}>
        <Icon name="chevron" size={12} style={{transform:collapsed.has(node.path)?undefined:'rotate(90deg)'}}/>
        <Icon name="folder" size={14}/><span>{node.name}</span>
      </button>
      {!collapsed.has(node.path)&&<div role="group" className="tree-files">{treeNodes(node.children,depth+1)}</div>}
    </div>);
  }

  const viewer=!selection.path?<div className="panel-empty file-viewer-empty"><Icon name={isDiff?'edit':'file'} size={32}/>
    {isDiff?'选择文件查看差异':'选择文件'}</div>
    :isDiff&&!canPreview?<div className="panel-empty file-viewer-empty">{!currentList||currentList.loading?'正在确认文件变更…':'这个文件已无本对话的记录变更。'}</div>
    :!currentPreview||currentPreview.loading?<div className="panel-empty file-viewer-empty"><Spinner/>{isDiff?'读取变更差异…':'读取源码…'}</div>
    :currentPreview.error?<div className="inline-error" role="alert">{currentPreview.error}</div>
    :!file?<div className="panel-empty file-viewer-empty">文件预览暂不可用，请刷新后重试。</div>
    :!code?<div className="panel-empty file-viewer-empty">{!isDiff?'这个文件是空的。':status==='added'
      ?'新增了一个空文件。':status==='deleted'?'已删除这个空文件。':'这个文件当前没有文本差异。'}</div>
    :<div className={'code-view '+(wrap?'code-wrap':'')}>{String(code).split(/\r?\n/).map((line,index)=>{
      const diffClass=isDiff?(line.startsWith('+')&&!line.startsWith('+++')?'added'
        :line.startsWith('-')&&!line.startsWith('---')?'removed':line.startsWith('@@')?'hunk':''):'';
      return <div className={'code-line '+diffClass} key={index}><span>{isDiff?'':index+1}</span><code>{line||' '}</code></div>;
    })}</div>;

  return <div className="file-workspace">
    <section className="file-viewer" aria-label={isDiff?'文件差异查看器':'文件源码查看器'}>
      <div className="file-heading"><span title={selection.path}>{selection.path||(isDiff?'变更差异':'源码预览')}</span>
        <div className="file-preview-actions"><button className="icon-button" aria-label="自动换行" aria-pressed={wrap} title="自动换行" onClick={()=>setWrap(value=>!value)}><Icon name="read" size={13}/></button><button className="icon-button" aria-label="复制文件内容" title={copyState||'复制文件内容'} disabled={!code} onClick={()=>{void navigator.clipboard.writeText(String(code)).then(()=>setCopyState('已复制')).catch(()=>setCopyState('复制失败'));}}><Icon name={copyState==='已复制'?'check':'copy'} size={13}/></button><span className="file-preview-kind">{isDiff?'差异':'源码'}</span></div></div>
      {viewer}
      {file?.diff_truncated&&isDiff&&<p className="file-tracking-note">差异较大，当前预览已截断。</p>}
    </section>
    <section className="file-directory" aria-label={isDiff?'对话变更目录':'项目文件目录'}>
      <div className="file-inspector-summary file-directory-heading"><h3>{isDiff?'本对话变更':'项目文件'}</h3>
        <button className="icon-button" title={isDiff?'刷新对话变更':'刷新项目文件'} onClick={()=>setRefresh(value=>value+1)}><Icon name="refresh" size={14}/></button></div>

      <div className="file-search"><Icon name="search" size={14}/><input aria-label={isDiff?'搜索对话变更':'搜索项目文件'}
        placeholder={isDiff?'查找变更文件…':'查找项目文件…'} maxLength={300} value={selection.query}
        onChange={event=>onChange({query:event.target.value,collapsed:[]})}/></div>
      <div className="file-list-meta"><span>{!currentList||currentList.loading?'正在读取…':isDiff
        ?selection.query?rows.length+' 项匹配 · 共 '+changeCount+' 项变更':changeCount+' 项变更'
        :rows.length+' 个'+(selection.query?'匹配的':'')+'文件'}</span></div>
      {isDiff&&currentList?.data&&<div className="file-list-meta">{(['added','modified','deleted'] as ChangeStatus[]).map(kind=>
        <span className={'file-status '+kind} key={kind}>{changeLabels[kind]} {currentList.data?.change_summary?.[kind]??0}</span>)}</div>}
      {currentList?.error&&<div className="file-list-error" role="alert">{currentList.error}</div>}
      <div className="file-tree" role="tree" aria-label={isDiff?'变更文件树':'项目文件树'}>
        {!currentList||currentList.loading?<div className="panel-empty"><Spinner/>读取目录…</div>
          :rows.length?treeNodes(fileTree(rows)):!currentList.error&&<p className="small-note">{selection.query
            ?isDiff?'没有匹配的变更文件。':'没有匹配的项目文件。':isDiff?'本对话暂无记录到的文件变更。':'这个项目没有可浏览的文件。'}</p>}
      </div>
      {currentList?.data?.truncated&&<p className="file-tracking-note">当前目录未全部展开，搜索路径可以缩小范围。</p>}
      {isDiff&&<p className="file-tracking-note">仅含本对话文件工具的修改，对比首次编辑前。</p>}
    </section>
  </div>;
}

type InspectorProps={open:boolean;onOverlayChange:(overlay:boolean)=>void;ownerKey?:string;width:number;onResize:(width:number)=>void;chat?:ChatDetail;project?:Project;tab:InspectorTab;setTab:(tab:InspectorTab)=>void;filePath:string;fileOpenNonce?:number;openNonce?:number;setFilePath:(path:string)=>void;action:ActionFn;close:()=>void;notify:(text:string)=>void};
const panelDescriptions:Record<InspectorTab,string>={files:'浏览项目目录与源码',changes:'对比本对话的文件修改',activity:'任务控制、队列与工具',processes:'查看后台进程与输出',usage:'请求、缓存与上下文',extensions:'Skills 与 MCP'};
function InspectorWorkspace({open,onOverlayChange,ownerKey,width,onResize,chat,project,tab,setTab,filePath,fileOpenNonce,openNonce,setFilePath,action,close,notify}:InspectorProps){
  const [present,setPresent]=useState(open);
  useEffect(()=>{if(open){setPresent(true);return;}const timer=setTimeout(()=>setPresent(false),260);return()=>clearTimeout(timer);},[open]);
  const owner=ownerKey||chat?.id||'project:'+project?.id,storageKey='inspector:'+owner;
  const [view,setView]=useState(()=>{
    const saved=readLocal<unknown>(storageKey,null),restored=restoreInspectorView(saved,undefined,filePath);
    const requested=!!openNonce&&openNonce!==restored.lastOpenNonce;
    const legacyRequest=!saved&&tab!=='files'||!!saved&&!restored.newTab&&tab!==restored.active;
    const fileRequest=openNonce===undefined&&!!filePath&&!!fileOpenNonce;
    if(requested||legacyRequest||fileRequest){restored.tabs=restored.tabs.includes(tab)?restored.tabs:[...restored.tabs,tab];restored.active=tab;restored.newTab=false;}
    if(openNonce)restored.lastOpenNonce=openNonce;
    return restored;
  });
  const pane=useRef<HTMLElement>(null),resizeHandle=useRef<HTMLDivElement>(null);
  const drag=useRef<{pointerId:number;startX:number;startWidth:number}|null>(null);
  const [resizing,setResizing]=useState(false),[geometry,setGeometry]=useState({available:0,overlay:window.innerWidth<=1100});
  useLayoutEffect(()=>onOverlayChange(geometry.overlay),[geometry.overlay,onOverlayChange]);
  useEffect(()=>{if(open&&geometry.overlay)pane.current?.querySelector<HTMLButtonElement>('.inspector-return')?.focus();},[open,geometry.overlay]);
  const bounds=panelBounds(geometry.available||1000,geometry.overlay);
  const displayWidth=clampPanelWidth(width,bounds);
  useLayoutEffect(()=>{
    const element=pane.current,workspace=element?.parentElement;if(!element||!workspace)return;
    const media=window.matchMedia('(max-width:1100px)');
    const measure=()=>{const available=workspace.getBoundingClientRect().width;const overlay=media.matches||available<700;
      setGeometry(old=>old.available===available&&old.overlay===overlay?old:{available,overlay});};
    measure();const observer=new ResizeObserver(measure);observer.observe(workspace);media.addEventListener('change',measure);
    return()=>{observer.disconnect();media.removeEventListener('change',measure);const pointer=drag.current;const handle=resizeHandle.current;
      if(pointer&&handle?.hasPointerCapture(pointer.pointerId))handle.releasePointerCapture(pointer.pointerId);drag.current=null;};
  },[]);
  function endResize(event:ReactPointerEvent<HTMLDivElement>){
    if(drag.current?.pointerId!==event.pointerId)return;
    drag.current=null;setResizing(false);
    if(event.currentTarget.hasPointerCapture(event.pointerId))event.currentTarget.releasePointerCapture(event.pointerId);
  }
  function beginResize(event:ReactPointerEvent<HTMLDivElement>){
    if(event.button!==0||!event.isPrimary)return;
    event.preventDefault();event.currentTarget.focus();
    drag.current={pointerId:event.pointerId,startX:event.clientX,startWidth:pane.current?.getBoundingClientRect().width||displayWidth};
    event.currentTarget.setPointerCapture(event.pointerId);setResizing(true);
  }
  function moveResize(event:ReactPointerEvent<HTMLDivElement>){
    const current=drag.current;if(!current||current.pointerId!==event.pointerId)return;
    const raw=current.startWidth-(event.clientX-current.startX);
    if(raw<PANEL_CLOSE_THRESHOLD){endResize(event);close();return;}
    onResize(clampPanelWidth(raw,bounds));
  }
  function keyResize(event:ReactKeyboardEvent<HTMLDivElement>){
    if(event.nativeEvent.isComposing||event.keyCode===229)return;
    const step=event.shiftKey?80:20;
    const next=event.key==='ArrowLeft'?displayWidth+step:event.key==='ArrowRight'?displayWidth-step
      :event.key==='Home'?bounds.min:event.key==='End'?bounds.max:null;
    if(event.key==='Escape'){event.preventDefault();close();return;}
    if(next===null)return;event.preventDefault();
    if(next<PANEL_CLOSE_THRESHOLD&&event.key==='ArrowRight'){close();return;}
    onResize(clampPanelWidth(next,bounds));
  }
  const previousPropTab=useRef(tab),previousFilePath=useRef(filePath),previousFileOpen=useRef(fileOpenNonce);
  const selectedChat=chat?.project_id===project?.id?chat:undefined;
  const toolResults=selectedChat?.messages.reduce((sum,message)=>sum+(message.trace?.entries.filter(entry=>entry.kind==='tool_result').length||0),0)||0;
  const active=view.active,isFile=!view.newTab&&view.tabs.length>0&&(active==='files'||active==='changes');
  useEffect(()=>writeLocal(storageKey,view),[storageKey,view]);
  useEffect(()=>{if(view.tabs.length&&!view.newTab)setTab(view.active);},[storageKey]);
  useEffect(()=>{
    if(previousPropTab.current===tab)return;
    previousPropTab.current=tab;
    setView(current=>({...current,tabs:current.tabs.includes(tab)?current.tabs:[...current.tabs,tab],active:tab,newTab:false}));
  },[tab]);
  useEffect(()=>{
    if(!openNonce)return;
    setView(current=>current.lastOpenNonce===openNonce?current:{...current,
      tabs:current.tabs.includes(tab)?current.tabs:[...current.tabs,tab],active:tab,newTab:false,lastOpenNonce:openNonce});
  },[openNonce,tab]);
  useEffect(()=>{
    if(previousFilePath.current===filePath&&previousFileOpen.current===fileOpenNonce)return;
    previousFilePath.current=filePath;previousFileOpen.current=fileOpenNonce;
    const open=!!filePath&&tab==='files';
    setView(current=>{
      const files={...current.files,path:filePath,collapsed:current.files.collapsed.filter(path=>!parentDirectories(filePath).includes(path))};
      if(!open)return {...current,files};
      if(!current.newTab&&current.active==='files'&&current.tabs.includes('files')&&current.files.path===filePath)return current;
      return {...current,files,tabs:current.tabs.includes('files')?current.tabs:[...current.tabs,'files'],active:'files',newTab:false};
    });
    if(open)setTab('files');
  },[filePath,tab,fileOpenNonce]);

  function selectTab(next:InspectorTab){
    setView(current=>({...current,tabs:current.tabs.includes(next)?current.tabs:[...current.tabs,next],active:next,newTab:false}));
    setTab(next);
  }
  function closeTab(next:InspectorTab){
    const tabs=view.tabs.filter(item=>item!==next);
    const active=view.active===next?(tabs[Math.max(0,view.tabs.indexOf(next)-1)]||tabs[0]||'files'):view.active;
    setView(current=>({...current,tabs,active,newTab:current.newTab||!tabs.length}));
    if(tabs.length&&!view.newTab)setTab(active);
  }
  function updateSelection(scope:FileScope,value:Partial<FileSelection>){
    setView(current=>({...current,[scope]:{...current[scope],...value}}));
  }

  return <aside ref={pane} id={'inspector-'+owner} aria-hidden={!open} inert={!open} className={'inspector surface-panel '+(!open?'inspector-closed ':'')+(isFile?'inspector-file-browser ':'')+(geometry.overlay?'inspector-overlay ':'')+(resizing?'inspector-resizing':'')}
    style={{width:geometry.overlay||open?displayWidth:0}}>
    <div className="inspector-body" style={{width:displayWidth}}>
    {(open||present)&&<>
    <div ref={resizeHandle} className="inspector-resize-handle" role="separator" tabIndex={0} aria-orientation="vertical"
      aria-label="调整右侧面板宽度" aria-controls={'inspector-'+owner} aria-valuemin={bounds.min} aria-valuemax={bounds.max}
      aria-valuenow={displayWidth} aria-valuetext={displayWidth+' 像素'} title="拖动调整；方向键调整，Home/End 最小/最大，Esc 收起"
      onPointerDown={beginResize} onPointerMove={moveResize} onPointerUp={endResize} onPointerCancel={endResize}
      onLostPointerCapture={()=>{drag.current=null;setResizing(false);}} onKeyDown={keyResize}/>

    <div className="inspector-browser-tabs"><button className="icon-button inspector-return" aria-label="返回聊天" title="返回聊天" onClick={close}><Icon name="back" size={16}/></button><div className="inspector-tab-strip" role="tablist" aria-label="检查器标签" onKeyDown={event=>{
      if(!(event.target instanceof HTMLElement)||event.target.getAttribute('role')!=='tab')return;
      const tabs=Array.from(event.currentTarget.querySelectorAll<HTMLButtonElement>('[role="tab"]')),index=tabs.indexOf(event.target as HTMLButtonElement);
      const next=event.key==='ArrowRight'?(index+1)%tabs.length:event.key==='ArrowLeft'?(index-1+tabs.length)%tabs.length:event.key==='Home'?0:event.key==='End'?tabs.length-1:null;
      if(next!==null){event.preventDefault();tabs[next].focus();tabs[next].click();}
    }}>
      {view.tabs.map(key=><div className={'inspector-browser-tab '+(!view.newTab&&key===active?'active':'')} key={key}>
        <button role="tab" tabIndex={!view.newTab&&key===active?0:-1} aria-selected={!view.newTab&&key===active} onClick={()=>selectTab(key)}><Icon name={inspectorTabTypes[key].icon} size={14}/>{inspectorTabTypes[key].title}</button>
        <button className="tab-close icon-button" aria-label={'关闭'+inspectorTabTypes[key].title+'标签'} onClick={()=>closeTab(key)}><Icon name="close" size={12}/></button>
      </div>)}
      {(view.newTab||!view.tabs.length)&&<div className="inspector-browser-tab active inspector-new-tab">
        <button role="tab" aria-selected={true} onClick={()=>setView(current=>({...current,newTab:true}))}><Icon name="plus" size={14}/>新标签页</button>
        {view.tabs.length>0&&<button className="tab-close icon-button" aria-label="关闭新标签页" onClick={()=>{setView(current=>({...current,newTab:false}));setTab(view.active);}}><Icon name="close" size={12}/></button>}
      </div>}
    </div><button className="icon-button inspector-tab-add" aria-label="添加检查器标签" title="新标签页"
      onClick={()=>setView(current=>({...current,newTab:true}))}><Icon name="plus" size={15}/></button></div>
    <div className={'inspector-scroll '+(isFile?'inspector-file-content':'')}>
      {view.newTab||!view.tabs.length?<div className="inspector-new-tab-page"><h2>工具</h2>
        <div className="inspector-panel-grid">{(Object.keys(inspectorTabTypes) as InspectorTab[]).map(key=>
          <button className="inspector-panel-option" title={panelDescriptions[key]} key={key} onClick={()=>selectTab(key)}>
            <Icon name={inspectorTabTypes[key].icon} size={16}/><strong>{inspectorTabTypes[key].title}</strong>
            {key==='processes'&&selectedChat&&groupProcesses(selectedChat.processes).active.length>0?<small className="success">{groupProcesses(selectedChat.processes).active.length} 运行中</small>:view.tabs.includes(key)?<small>已打开</small>:<Icon name="chevron" size={12}/>}
          </button>)}</div></div>
        :!project?<div className="panel-empty">选择一个项目查看文件与任务详情。</div>
        :active==='files'?<FilePane key={fileScopeKey('files',project.id)} scope="files" project={project} chat={selectedChat}
          selection={view.files} onChange={value=>updateSelection('files',value)} filePath={filePath} setFilePath={setFilePath} toolResults={toolResults}/>
        :!selectedChat?<div className="panel-empty">{active==='changes'?'选择一个对话查看它记录的文件变更。项目目录可在“项目文件”中浏览。':'选择一个对话查看运行、进程与用量详情。'}</div>
        :active==='changes'?<FilePane key={fileScopeKey('changes',project.id,selectedChat.id)} scope="changes" project={project} chat={selectedChat}
          selection={view.changes} onChange={value=>updateSelection('changes',value)} filePath={filePath} setFilePath={setFilePath} toolResults={toolResults}/>
        :active==='usage'?<UsagePanel chat={selectedChat}/>
        :active==='processes'?<ProcessesPanel enabled={open} key={selectedChat.id} chat={selectedChat} action={action} notify={notify}/>
        :active==='extensions'?<Capabilities chat={selectedChat} action={action}/>
        :<><header className="panel-heading"><div><h2>运行概览</h2><p>{phaseLabel(selectedChat.phase)}阶段</p></div><span className={'process-status '+(isBusy(selectedChat.status)?'working':'muted')}>{statusLabel(selectedChat.status)}</span></header>
          <div className="run-overview"><span><Icon name="history" size={15}/><strong>{selectedChat.queue.length}</strong>排队输入</span><span><Icon name="terminal" size={15}/><strong>{groupProcesses(selectedChat.processes).active.length}</strong>活动进程</span><span><Icon name="shield" size={15}/><strong>{selectedChat.permissions.length}</strong>等待审批</span></div>
          {selectedChat.permissions.length>0&&<p className="panel-hint">有操作等待批准，请在聊天中查看具体内容。</p>}
          {selectedChat.status==='busy'&&<p className="panel-hint">会话被另一界面占用，请先在该界面释放。</p>}
          <QueuePanel chat={selectedChat} action={action} notify={notify}/>
          <div className="inspector-section"><details className="panel-disclosure"><summary>会话维护<Icon name="down" size={12}/></summary><div className="row-actions"><button disabled={isBusy(selectedChat.status)||!selectedChat.sdk_session_id} onClick={()=>void action('compact')}><Icon name="archive" size={14}/>压缩上下文</button><button disabled={isBusy(selectedChat.status)||!selectedChat.sdk_session_id} onClick={()=>void action('release')}><Icon name="link" size={14}/>释放会话占用</button></div></details></div>
          <div className="inspector-section"><details className="visible-tools"><summary>可见工具 · {selectedChat.tools.length}<Icon name="down" size={12}/></summary>
            {selectedChat.tools.map((tool,index)=><div className="tool-catalog-row" key={tool.name||index}>
              <div><Icon name={toolIconName(tool.name)} size={15}/><code>{tool.name}</code><span className="tag">{tool.should_defer?'按需发现':({read:'读取',write:'写入',command:'命令'} as Dict)[tool.category]||tool.category}</span></div>
              <p>{tool.description}</p>{tool.allowed_phases?.length>0&&<small>可用阶段：{tool.allowed_phases.join('、')}</small>}
            </div>)}
          </details></div></>}
    </div></>}
    </div>
  </aside>;
}
export function Inspector(props:InspectorProps){
  const owner=props.ownerKey||props.chat?.id||'project:'+props.project?.id;
  return <InspectorWorkspace key={owner} {...props}/>;
}
