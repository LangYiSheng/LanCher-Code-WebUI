"""项目、对话、SDK owner 与项目内前台调度。"""
from __future__ import annotations
import asyncio
import json
import logging
import os
import time
from collections import deque
from contextlib import aclosing
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from lancher_code.agent.skills import SkillsService
from lancher_code.contracts.json import json_value
from lancher_code.contracts.control import validate_runtime_axes
from lancher_code.config.paths import get_project_permissions_path
from lancher_code.mcp import MCPClientManager, load_mcp_config
from lancher_code.permissions.storage import PermissionStorage
from lancher_code.logging_system import register_sensitive_values
from lancher_code.sdk import create_agent, PermissionResolution
from lancher_code.sessions.codec import SessionCodec
from lancher_code.sessions.repository import ProjectSessionRepository
from lancher_code.sessions.storage import SessionBusyError,SessionRepositoryError
from lancher_code.tools import create_default_tool_registry
from lancher_code.usage.ledger import RequestUsageRecord,summarize_records

from .configuration import ConfigurationService
from .context_preview import saved_context_usage
from lancher_code.providers.catalog import resolve_model
from lancher_code.providers.reasoning import EFFORT_LEVELS, validate_effort
from lancher_code.errors import ConfigError
from .files import list_files,read_file,validate_reference,resolve_project_file,file_change
from lancher_code.permissions.engine import PermissionEngine
from lancher_code.contracts.tools import ToolCall
from lancher_code.tools.context import ToolContext
from .store import Store

log=logging.getLogger(__name__)


class WebError(Exception):
    def __init__(self,message,status=400):
        super().__init__(message);self.status=status


def now():
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Owner:
    agent:object
    permissions:dict=field(default_factory=dict)
    task:asyncio.Task|None=None
    access_at:float=field(default_factory=time.monotonic)
    progress_at:float=0.0
    config_pending:bool=False
    queue_before_config:bool=False
    pending_domains:set=field(default_factory=set)
    process_signature:str=""
    dispatch_next:bool=False
    manual_pause:bool=False


class AppManager:
    def __init__(self,root,user_home=None,provider_factory=None,enable_mcp=True,resource_root=None):
        self.root=Path(root).resolve();self.data=self.root/'data'
        self.user_home=Path(user_home or Path.home())
        self.configuration=ConfigurationService(self.root,user_home=self.user_home)
        self.provider_factory=provider_factory;self.enable_mcp=enable_mcp
        self.store=Store(self.data/'webui.sqlite3')
        self.projects=self.store.load('projects');self.chats=self.store.load('chats')
        self.preferences={'theme':'system','reduce_transparency':False,'reduce_motion':False,
                          **self.store.load('preferences').get('web',{})}
        self.preview_registry=create_default_tool_registry()
        self.owners={};self.owner_locks={};self.project_jobs={};self.drainers={}
        self.snapshot_cache={};self.server_id=uuid4().hex;self.signal=asyncio.Event()
        self.closing=False;self.closed=False;self.maintenance=None
        self.shutdown_callback=None
        self.sdk_snapshot=json.loads((Path(resource_root or self.root)/'vendor/snapshot.json').read_text(encoding='utf-8-sig'))

    async def start(self):
        for chat in self.chats.values():
            # 仅迁移旧版没有任务和 SDK 历史的空登记，不能把已接受的输入降回草稿。
            if chat.get('draft') or self._legacy_empty_chat(chat):
                chat['draft']=True;self.store.remove('chats',chat['id'])
            else:
                chat['draft']=False
            if chat['status'] in {'queued','running','waiting_permission','stopping','compacting'}:
                chat['status']='interrupted'
            self._save(chat)
        await self.refresh_projects()
        self.maintenance=asyncio.create_task(self._maintain(),name='webui-owner-maintenance')

    def get_project(self,identity):
        if identity not in self.projects: raise WebError('项目不存在。',404)
        return self.projects[identity]

    def get_chat(self,identity):
        if identity not in self.chats: raise WebError('对话不存在。',404)
        return self.chats[identity]

    def _legacy_empty_chat(self,chat):
        if 'draft' in chat or chat.get('sdk_session_id') or chat.get('first_turn_accepted_at'):
            return False
        if chat.get('status','idle')!='idle' or any(chat.get(key) for key in
                ('pending_task','result','queue','pending_inputs','plan','plan_snapshot','processes')):
            return False
        return not self.store.requests(chat_id=chat['id']) and not self.store.file_baselines(chat['id'])

    def _save(self,chat):
        chat['updated_at']=now()
        if not chat.get('draft'):self.store.put('chats',chat['id'],chat)

    def _promote(self,chat):
        if chat.get('draft'):
            chat['draft']=False;chat['first_turn_accepted_at']=now()

    def emit(self,data,chat=None,project=None):
        if self.closed:return
        if chat and chat.get('draft'):
            # 空对话只广播有限的界面元数据，不把 SDK 消息和队列正文写进重放缓存。
            if data.get('kind') not in {'chat_state','capabilities_updated','mcp_progress_updated','processes_updated','lab_log'}:
                return
            data={key:value for key,value in data.items() if key in {'kind','chat','mcp','progress','processes','text'}}
        if chat:
            data={**data,'chat_id':chat['id'],'project_id':chat['project_id'],
                  'sdk_session_id':chat.get('sdk_session_id'),'run_id':chat.get('run_id')}
        elif project:data={**data,'project_id':project['id']}
        if 'sequence' in data:data={**data,'sdk_sequence':data['sequence']};data.pop('sequence')
        event=self.store.event({**data,'timestamp':now()})
        signal=self.signal;self.signal=asyncio.Event();signal.set()
        return event

    def effort_state(self,chat):
        """不用创建 owner 即可展示档位；未知能力不能当成不支持。"""
        owner=self.owners.get(chat['id'])
        if owner:
            agent=owner.agent
            return {'reasoning_effort':agent.reasoning_effort,'effort_levels':list(agent.effort_levels),
                    'effort_known':agent.effort_known}
        effort=chat.get('reasoning_effort','auto')
        try:
            config=self._config();ref=chat.get('model_ref') or config.default_model
            if ref not in {provider_id+'/'+model_id for provider_id,provider in config.providers.items() for model_id in provider.models}:
                ref=config.default_model
            provider=resolve_model(config.providers,ref)
            cap=validate_effort(provider.protocol,provider.metadata,'auto')
            levels=('auto',*cap.levels) if cap.levels is not None else EFFORT_LEVELS
            return {'reasoning_effort':effort if effort in levels else 'auto',
                    'effort_levels':list(levels),'effort_known':cap.levels is not None}
        except Exception:
            return {'reasoning_effort':effort if effort in EFFORT_LEVELS else 'auto',
                    'effort_levels':list(EFFORT_LEVELS),'effort_known':False}

    def changed(self,chat):
        chat.update(self.effort_state(chat))
        self._save(chat);self.emit({'kind':'chat_state','chat':dict(chat)},chat=chat)

    def _config(self):
        try:return self.configuration.get_config()
        except Exception as exc:raise WebError(str(exc),409) from exc

    def project_root(self,project_id):
        project=self.get_project(project_id);root=Path(project['path'])
        if not root.is_dir():project['available']=False;raise WebError('项目目录已不存在，请重新定位。',409)
        return root.resolve()

    def _preview_access(self,project_id):
        root=self.project_root(project_id)
        storage=self.configuration.make_permission_storage(root)
        return PermissionEngine(storage),ToolContext(cwd=root,project_root=root,timeout_seconds=5,work_phase='discuss',execution_access='project')

    def _check_preview(self,engine,context,path,tool_name='read_file'):
        arguments={'path':path} if tool_name=='read_file' else {'pattern':'**/*'}
        call=ToolCall(0,'web-preview',tool_name,arguments,json.dumps(arguments))
        check=engine.evaluate(call=call,tool=self.preview_registry.get(tool_name).definition,context=context)
        if check.decision!='allow':raise WebError(check.reason_message or '共享权限规则拒绝读取文件。',403)

    def project_files(self,project_id,q='',chat_id=None,scope='files'):
        if scope not in {'files','changes'}:raise WebError('不支持的文件列表范围。')
        if scope=='changes' and not chat_id:raise WebError('查看对话变更需要选择对话。')
        engine,context=self._preview_access(project_id)
        self._check_preview(engine,context,'',tool_name='glob')
        if not isinstance(q,str) or len(q)>300:raise WebError('文件检索词无效。')
        baseline={}
        if chat_id:
            chat=self.get_chat(chat_id)
            if chat['project_id']!=project_id:raise WebError('文件列表不属于当前对话。',403)
            baseline=self.store.file_baselines(chat_id)
        changes={}
        for path,before in baseline.items():
            try:
                self._check_preview(engine,context,path)
                change=file_change(context.cwd,path,before)
                if change['status']!='unchanged':changes[path]=change
            except (ValueError,OSError,WebError):continue
        summary={key:sum(row['status']==key for row in changes.values()) for key in ('added','modified','deleted')}
        if scope=='changes':
            result={'files':[row for path,row in sorted(changes.items()) if q.casefold() in path.casefold()],
                    'truncated':False,'query':q}
        else:
            result=list_files(context.cwd,q);visible=[]
            for row in result['files']:
                try:self._check_preview(engine,context,row['path'])
                except WebError:continue
                visible.append({**row,'status':changes.get(row['path'],{}).get('status','unchanged')})
            result={**result,'files':visible}
        return {**result,'scope':scope,'change_count':len(changes),'change_summary':summary,
                'change_tracking':'native_file_tools'}

    def preview_project_file(self,project_id,path):
        engine,context=self._preview_access(project_id)
        resolve_project_file(context.cwd,path);self._check_preview(engine,context,path)
        return read_file(context.cwd,path)

    def preview_file(self,chat_id,path):
        chat=self.get_chat(chat_id);engine,context=self._preview_access(chat['project_id'])
        target=resolve_project_file(context.cwd,path);self._check_preview(engine,context,path)
        relative=target.relative_to(context.cwd).as_posix()
        baseline=self.store.file_baselines(chat_id)
        return read_file(context.cwd,relative,baseline=baseline if relative in baseline else None)

    def _capture_baseline(self,chat,event):
        call=event.tool_call
        if event.kind!='tool_call_started' or not call or call.tool_name not in {'write_file','edit_file','delete_file'}:return
        path=call.arguments.get('path')
        if not isinstance(path,str):return
        root=self.project_root(chat['project_id'])
        try:
            target=(root/path).resolve();relative=target.relative_to(root).as_posix()
            resolve_project_file(root,relative)
            engine,context=self._preview_access(chat['project_id'])
            existing=self.store.file_baselines(chat['id'])
            candidates=[target]
            if target.is_dir():
                if call.tool_name!='delete_file' or call.arguments.get('recursive') is not True:return
                # 递归删除也记录可预览的后代；总大小有界，且继续遵守读取权限。
                candidates=[target/row['path'] for row in list_files(target)['files']]
            budget=16*1024*1024
            for candidate in candidates:
                try:
                    name=candidate.relative_to(root).as_posix()
                    resolve_project_file(root,name)
                    if name in existing:continue
                    self._check_preview(engine,context,name)
                    if candidate.exists():
                        size=candidate.stat().st_size
                        if not candidate.is_file() or size>1024*1024 or size>budget:continue
                        content=candidate.read_text(encoding='utf-8-sig');budget-=size
                    else:content=None
                    self.store.file_baseline(chat['id'],name,content)
                except (ValueError,OSError,WebError):continue
        except (ValueError,OSError,WebError):pass

    async def add_project(self,path,name=None):
        if not isinstance(path,str) or not path.strip():raise WebError('请选择工作文件夹。')
        supplied=Path(path).expanduser()
        if not supplied.is_absolute() or not supplied.is_dir():raise WebError('需要已存在的绝对工作目录。')
        root=supplied.resolve();key=os.path.normcase(str(root))
        for project in self.projects.values():
            if os.path.normcase(project['path'])==key:return dict(project)
        project={'id':uuid4().hex,'name':name.strip() if name and name.strip() else root.name or str(root),
                 'path':str(root),'created_at':now(),'available':True,'pinned':False,'issues':[]}
        self.projects[project['id']]=project;self.store.put('projects',project['id'],project)
        await self.refresh_project(project['id']);self.emit({'kind':'project_state','project':project},project=project)
        return dict(project)

    async def patch_project(self,identity,payload):
        project=self.get_project(identity)
        if 'name' in payload:
            if not str(payload['name']).strip():raise WebError('项目名称不能为空。')
            project['name']=str(payload['name']).strip()[:100]
        if 'pinned' in payload:project['pinned']=bool(payload['pinned'])
        self.store.put('projects',identity,project);self.emit({'kind':'project_state','project':project},project=project)
        return dict(project)

    def project_impact(self,identity):
        project=self.get_project(identity)
        members=[chat for chat in self.chats.values() if chat['project_id']==identity and not chat.get('draft')]
        running=[{'id':chat['id'],'title':chat['title'],'status':chat['status']} for chat in members
                 if self._active(chat['id']) or chat['status']=='queued']
        processes=[]
        for chat in members:
            owner=self.owners.get(chat['id'])
            if owner:
                processes.extend({**row,'chat_id':chat['id'],'chat_title':chat['title']} for row in owner.agent.list_processes()
                                 if row['status'] in {'starting','running'})
        return {'project_id':identity,'name':project['name'],'path':project['path'],'conversation_count':len(members),
                'tasks':running,'processes':processes,'files_preserved':True,'history_preserved':True}

    async def remove_project(self,identity,confirmed=False):
        project=self.get_project(identity)
        members=[chat for chat in self.chats.values() if chat['project_id']==identity]
        active=[chat for chat in members if self._active(chat['id']) or chat['status']=='queued' or self._process_count(chat['id'])]
        if active and not confirmed:raise WebError('项目有运行任务或后台进程，请确认停止后移除。',409)
        for chat in members:
            await self.stop(chat['id'],'session');await self.release(chat['id'],force=True)
            self.store.remove('chats',chat['id']);self.chats.pop(chat['id'],None)
        self.projects.pop(identity);self.store.remove('projects',identity)
        self.emit({'kind':'project_removed','project_id':identity})
        return {'removed':True,'files_preserved':True}

    async def refresh_projects(self):
        for identity in tuple(self.projects):await self.refresh_project(identity)

    async def refresh_project(self,identity):
        project=self.get_project(identity);root=Path(project['path']);project['available']=root.is_dir()
        if not project['available']:return
        listing=ProjectSessionRepository(root).list_sessions()
        project['issues']=json_value(listing.issues)
        present=set()
        for info in listing.items:
            present.add(info.session_id)
            matches=[chat for chat in self.chats.values() if chat['project_id']==identity and chat.get('sdk_session_id')==info.session_id]
            if matches:
                chat=matches[0]
                if not self._active(chat['id']):
                    chat.update(title=info.title,archived=chat.get('archive_override',info.archived),model_ref=info.model_ref or chat.get('model_ref'))
            else:
                chat={'id':uuid4().hex,'project_id':identity,'sdk_session_id':info.session_id,'title':info.title,
                      'status':'idle','phase':'execute','access':'project','model_ref':info.model_ref,
                      'pinned':False,'archived':info.archived,'created_at':info.created_at.isoformat(),
                      'updated_at':info.updated_at.isoformat(),'pending_config':False,'queue_paused':False}
                self.chats[chat['id']]=chat
            chat['draft']=False;self.store.put('chats',chat['id'],chat)
            try:self._collect_usage(chat,state=self._read_snapshot(chat))
            except (OSError,SessionRepositoryError,ValueError):pass
        for chat in tuple(self.chats.values()):
            if chat['project_id']==identity and chat.get('sdk_session_id') and chat['sdk_session_id'] not in present and not self._active(chat['id']):
                self.chats.pop(chat['id']);self.store.remove('chats',chat['id'])
        self.store.put('projects',identity,project)

    async def create_chat(self,project_id,title='',model_ref=None,draft_id=None,phase=None,access=None,reasoning_effort=None):
        self.project_root(project_id)
        if draft_id is not None:
            if not isinstance(draft_id,str) or len(draft_id)!=32 or any(char not in '0123456789abcdefABCDEF' for char in draft_id):
                raise WebError('草稿标识需要 32 位 UUID 十六进制字符串。')
            identity=draft_id.lower()
            existing=self.chats.get(identity)
            if existing:
                if existing.get('draft') and existing['project_id']==project_id:return dict(existing)
                raise WebError('这个标识已属于正式对话或其他项目，请保留原对话并创建新的草稿。',409)
            if any(chat.get('sdk_session_id')==identity for chat in self.chats.values()):
                raise WebError('这个标识已属于 SDK 会话，不能作为空白草稿复用。',409)
        else:identity=uuid4().hex
        config=None
        try:
            config=self._config();model_ref=model_ref or config.default_model
            default_phase=config.runtime.work_phase;default_access=config.runtime.execution_access
        except WebError:default_phase='execute';default_access='project'
        phase,access=validate_runtime_axes(phase or default_phase,access or default_access)
        effort='auto' if reasoning_effort is None else reasoning_effort
        if config is not None:
            resolved=resolve_model(config.providers,model_ref)
            validate_effort(resolved.protocol,resolved.metadata,effort)
        else:validate_effort('openai',None,effort)
        chat={'id':identity,'project_id':project_id,'sdk_session_id':None,'draft':True,'title':title.strip() or '新对话',
              'status':'idle','phase':phase,'access':access,'model_ref':model_ref,'reasoning_effort':effort,'pinned':False,'archived':False,
              'created_at':now(),'updated_at':now(),'pending_config':False,'queue_paused':False}
        self.chats[identity]=chat;self.changed(chat);return dict(chat)

    def resolve_chat(self,project_id,sdk_uuid):
        for chat in self.chats.values():
            if chat['project_id']==project_id and chat.get('sdk_session_id')==sdk_uuid:return chat
        raise WebError('当前项目中没有这个 UUID 的对话。',404)

    def _active(self,chat_id):
        owner=self.owners.get(chat_id)
        return bool(owner and owner.task and not owner.task.done())

    def _process_count(self,chat_id):
        owner=self.owners.get(chat_id)
        return owner.agent.application_process_count if owner else 0

    def _read_snapshot(self,chat):
        owner=self.owners.get(chat['id'])
        if owner:return json_value(owner.agent.state)
        if not chat.get('sdk_session_id'):return {'messages':[],'request_usage':{},'pending_inputs':[]}
        root=self.project_root(chat['project_id']);repo=ProjectSessionRepository(root)
        event_path=repo.paths(chat['sdk_session_id']).events
        stat=event_path.stat();key=(chat['id'],stat.st_mtime_ns,stat.st_size)
        if key in self.snapshot_cache:return self.snapshot_cache[key]
        raw=SessionCodec.project(repo.read(chat['sdk_session_id']))
        state,transcript,_,model_ref=SessionCodec.decode(raw,chat['sdk_session_id'])
        data=json_value(state);chat.update(phase=state.work_phase,access=state.execution_access,model_ref=model_ref or chat.get('model_ref'),reasoning_effort=state.reasoning_effort)
        try:
            config=self._config();provider=resolve_model(config.providers,chat.get('model_ref') or config.default_model)
            data['_context_preview']=saved_context_usage(state,transcript,provider)
        except Exception:
            data['_context_preview']={'tokens':None,'source':'unknown','window':None,'snapshot':True}
        self.snapshot_cache={k:v for k,v in self.snapshot_cache.items() if k[0]!=chat['id']}
        self.snapshot_cache[key]=data;return data

    def _collect_usage(self,chat,owner=None,state=None):
        state=state or self._read_snapshot(chat)
        for record in state.get('request_usage',{}).values():
            server_id=self.server_id if owner and record.get('run_id')==owner.agent.run_id else None
            self.store.request(record,chat['project_id'],chat['id'],server_id)

    def _usage(self,chat,state,owner=None):
        self._collect_usage(chat,owner,state)
        def summary(records):
            return json_value(summarize_records(RequestUsageRecord.from_dict(record) for record in records))
        session=list(state.get('request_usage',{}).values())
        answer_id=next((message['id'] for message in reversed(state.get('messages',[])) if message['role']=='assistant'),None)
        answer=[record for record in session if record.get('message_id')==answer_id]
        return {'answer':summary(answer),'session':summary(session),
                'project':summary(self.store.requests(project_id=chat['project_id'])),
                'server':summary(self.store.requests(server_id=self.server_id))}

    async def bootstrap(self):
        await self.refresh_projects()
        models=[];config_error=None;ui={}
        try:
            config=self._config();ui=json_value(config.ui)
            for provider_id,provider in config.providers.items():
                for model_id,model in provider.models.items():
                    reference=provider_id+'/'+model_id
                    resolved=resolve_model(config.providers,reference)
                    cap=validate_effort(resolved.protocol,resolved.metadata,'auto')
                    models.append({'id':reference,'name':model.display_name or model.model_name,
                                   'provider':provider.name,'default':reference==config.default_model,
                                   'metadata':json_value(resolved.metadata),'api_mode':resolved.api_mode,
                                   'effort_levels':list(('auto',*cap.levels) if cap.levels is not None else EFFORT_LEVELS),
                                   'effort_known':cap.levels is not None})
        except WebError as exc:config_error=str(exc)
        from .commands import command_catalog
        return {'name':'LanCher Code WebUI','sdk_commit':self.sdk_snapshot['commit'],
                'projects':list(self.projects.values()),'chats':[{**chat,**self.effort_state(chat)} for chat in self.chats.values()],'models':models,
                'ui':ui,'preferences':self.preferences,'config_error':config_error,
                'watermark':self.store.watermark,'commands':command_catalog(),
                'execution':'本机运行 · SDK 原生工具','config_path':str(self.user_home/'.lancher/lancher.yaml')}

    async def chat_detail(self,chat_id,before=None,limit=50):
        chat=self.get_chat(chat_id);owner=self.owners.get(chat_id)
        if owner:owner.access_at=time.monotonic()
        try:
            state=self._read_snapshot(chat)
        except (OSError,SessionRepositoryError) as exc:
            raise WebError(str(exc),409) from exc
        messages=state.get('messages',[]);end=len(messages) if before is None else min(len(messages),max(0,before))
        start=max(0,end-limit)
        context=state.get('_context_preview') or {'tokens':None,'source':'unknown','window':None};skills=[];mcp=[];processes=[]
        if owner:
            skills=owner.agent.capabilities.list_skills();mcp=owner.agent.capabilities.mcp_status()
            processes=owner.agent.list_processes()
            try:context=owner.agent.capabilities.context_usage();context['window']=owner.agent.context_window
            except Exception:context={'tokens':None,'source':'unknown','window':owner.agent.context_window}
            tools=json_value(owner.agent.capabilities.visible_tools())
            chat.update(phase=owner.agent.work_phase,access=owner.agent.execution_access,model_ref=owner.agent.model_ref,
                        queue_paused=owner.manual_pause or owner.agent.queue_paused,run_id=owner.agent.run_id)
        else:
            root=self.project_root(chat['project_id'])
            skills=json_value(SkillsService(root,user_root=self.user_home).list_skills())
            tools=json_value(create_default_tool_registry().list_definitions(include_deferred=True))
            processes=list(state.get('execution',{}).get('processes',{}).values())
        chat.update(self.effort_state(chat))
        if not chat.get('draft'):self.store.put('chats',chat_id,chat)
        usage=self._usage(chat,state,owner)
        return {**chat,'messages':messages[start:end],'has_more':start>0,'next_before':start,
                'message_count':len(messages),'queue':state.get('pending_inputs',[]),
                'permissions':list(owner.permissions.values()) if owner else [],
                'plan':state.get('plan_snapshot'),'tools':tools,'capabilities':{'skills':skills,'mcp':mcp},
                'model_notice':getattr(owner.agent,'model_notice',None) if owner else None,
                'context':context,'usage':usage,'processes':processes,'compactions':state.get('compaction_activities',{}),
                'result':chat.get('result'),'pending_task':chat.get('pending_task'),'watermark':self.store.watermark}

    async def _owner(self,chat_id):
        self.project_root(self.get_chat(chat_id)['project_id'])
        lock=self.owner_locks.setdefault(chat_id,asyncio.Lock())
        async with lock:
            if chat_id in self.owners:
                owner=self.owners[chat_id];owner.access_at=time.monotonic();return owner
            chat=self.get_chat(chat_id);root=self.project_root(chat['project_id']);config=self._config()
            agent_config=config.to_agent_config()
            # 同一事件循环中的项目调度额度必须一致，修改额度在服务重启后生效。
            if not hasattr(self,'execution_configs'):self.execution_configs={}
            from copy import deepcopy
            if chat['project_id'] not in self.execution_configs:self.execution_configs[chat['project_id']]=deepcopy(agent_config.execution)
            agent_config.execution=deepcopy(self.execution_configs[chat['project_id']])
            agent_config.runtime.work_phase=chat.get('phase','execute');agent_config.runtime.execution_access=chat.get('access','project')
            storage=PermissionStorage(project_rules_path=get_project_permissions_path(root),
                                      user_rules_path=self.user_home/'.lancher/permissions.yaml')
            mcp_manager=None
            if self.enable_mcp:
                configs,issues=self.configuration.get_mcp_config(root)
                register_sensitive_values(value for item in configs for value in (*item.env.values(),*item.headers.values()))
                mcp_manager=MCPClientManager(configs,issues=issues)
            agent=create_agent(agent_config,cwd=root,model_ref=config.default_model if chat.get('sdk_session_id') else chat.get('model_ref') or config.default_model,
                               permission_storage=storage,skills_service=SkillsService(root,user_root=self.user_home),
                               provider_factory=self.provider_factory,mcp_manager=mcp_manager,enable_mcp=False)
            try:
                if chat.get('sdk_session_id'):agent.resume_session(chat['sdk_session_id'])
                else:agent.set_effort(chat.get('reasoning_effort','auto'))
                chat['reasoning_effort']=agent.reasoning_effort
                owner=Owner(agent,manual_pause=bool(chat.get('queue_paused') or agent.queue_paused));self.owners[chat_id]=owner
                agent.subscribe(lambda event:self._on_event(chat,owner,event))
                agent.capabilities.add_mcp_progress_callback(lambda progress:self.emit({'kind':'capabilities_updated','progress':json_value(progress),'mcp':agent.capabilities.mcp_status()},chat=chat))
                agent.start_capabilities()
                chat['run_id']=agent.run_id
            except BaseException:
                await agent.close();self.owners.pop(chat_id,None);raise
            return owner

    def _on_event(self,chat,owner,event):
        if event.kind=='progress_updated':
            stamp=time.monotonic()
            if stamp-owner.progress_at<0.15:return
            owner.progress_at=stamp
        self._capture_baseline(chat,event)
        data=event.to_dict()
        if event.kind=='assistant_text_delta':data['message']=None
        chat['sdk_session_id']=event.session_id or chat.get('sdk_session_id')
        request=data.get('permission_request');resolution=data.get('permission_resolution')
        if event.kind=='permission_request_created' and request:
            owner.permissions[request['request_id']]=request;chat['status']='waiting_permission'
        elif event.kind in {'permission_request_resolved','permission_request_closed'}:
            if resolution:owner.permissions.pop(resolution['request_id'],None)
            elif request:owner.permissions.pop(request['request_id'],None)
            if chat['status']=='waiting_permission' and not owner.permissions:chat['status']='running'
        self.emit(data,chat=chat)
        if event.kind not in {'progress_updated','assistant_text_delta'}:
            self._collect_usage(chat,owner,json_value(owner.agent.state));self.changed(chat)
        # SDK 自动续接会越过其他聊天；在轮次边界交还项目 FIFO。
        items=owner.agent.pending_inputs
        if event.kind=='turn_completed' and items and items[0].delivery=='follow_up' and not owner.agent.queue_paused and not owner.manual_pause:
            owner.dispatch_next=True;owner.agent.pause_queue()

    async def patch_chat(self,chat_id,payload):
        chat=self.get_chat(chat_id)
        if chat.get('draft') and any(key in payload for key in {'phase','access','model_ref','reasoning_effort'}):
            if self._active(chat_id) or chat['status']=='queued':raise WebError('当前对话正在运行或排队。',409)
            phase,access=validate_runtime_axes(payload.get('phase',chat['phase']),payload.get('access',chat['access']))
            model_ref=payload.get('model_ref',chat.get('model_ref'))
            effort=payload.get('reasoning_effort',chat.get('reasoning_effort','auto'))
            if 'model_ref' in payload or 'reasoning_effort' in payload:
                if not isinstance(model_ref,str) or not model_ref.strip():raise WebError('请选择有效模型。')
                resolved=resolve_model(self._config().providers,model_ref)
                if 'reasoning_effort' in payload:validate_effort(resolved.protocol,resolved.metadata,effort)
                else:
                    try:validate_effort(resolved.protocol,resolved.metadata,effort)
                    except ConfigError:effort='auto'
            owner=self.owners.get(chat_id)
            if owner:
                if 'model_ref' in payload:owner.agent.switch_model(model_ref)
                if 'access' in payload:owner.agent.set_execution_access(access)
                if 'phase' in payload:owner.agent.set_phase(phase)
                if 'reasoning_effort' in payload:owner.agent.set_effort(effort)
                effort=owner.agent.reasoning_effort
            chat.update(phase=phase,access=access,model_ref=model_ref,reasoning_effort=effort)
        if any(key in payload for key in {'title','archived'}) and (self._active(chat_id) or chat['status']=='queued' or self._process_count(chat_id)):
            raise WebError('请先停止对话任务和后台进程。',409)
        sdk_id=chat.get('sdk_session_id')
        if sdk_id and any(key in payload for key in {'title','archived'}):
            await self.release(chat_id)
            repo=ProjectSessionRepository(self.project_root(chat['project_id']))
            if 'title' in payload:repo.rename(sdk_id,str(payload['title']).strip())
            if 'archived' in payload:
                if payload['archived']:repo.archive(sdk_id);chat.pop('archive_override',None)
                else:
                    chat['archive_override']=False
        if 'title' in payload:
            title=str(payload['title']).strip()
            if not title:raise WebError('对话标题不能为空。')
            chat['title']=title[:150]
        for key in ('pinned','archived'):
            if key in payload:chat[key]=bool(payload[key])
        self.changed(chat);return dict(chat)

    async def remove_chat(self,chat_id,confirmed=False):
        chat=self.get_chat(chat_id)
        if not confirmed:raise WebError('删除将移除对话记录及其计划工作区，请确认。',409)
        if self._active(chat_id) or chat['status']=='queued' or self._process_count(chat_id):raise WebError('先停止本对话和后台进程。',409)
        await self.release(chat_id)
        if chat.get('sdk_session_id'):ProjectSessionRepository(self.project_root(chat['project_id'])).remove(chat['sdk_session_id'])
        self.chats.pop(chat_id);self.store.remove('chats',chat_id);self.emit({'kind':'chat_removed','chat_id':chat_id})
        return {'removed':True,'project_files_preserved':True}

    async def submit(self,chat_id,prompt,attachments=None):
        if self.closing:raise WebError('服务正在退出。',503)
        chat=self.get_chat(chat_id);self.project_root(chat['project_id'])
        if chat.get('archived'):raise WebError('请先恢复归档对话。',409)
        if self._active(chat_id) or chat['status']=='queued':raise WebError('对话正在运行或排队，请追加到队列。',409)
        if not isinstance(prompt,str) or not prompt.strip():raise WebError('任务不能为空。')
        if len(prompt)>20000:raise WebError('任务超过输入限制。')
        self._config()
        paths=[]
        for path in attachments or []:
            validate_reference(self.project_root(chat['project_id']),path);paths.append(path)
        if paths:prompt=prompt+'\n\n选定项目文件（请按需使用读取工具）：\n'+'\n'.join(paths)
        if chat['title']=='新对话':chat['title']=prompt.strip()[:36]
        return await self._schedule(chat,{'kind':'turn','prompt':prompt})

    async def _schedule(self,chat,job):
        # 输入一经接受就成为正式对话；排队、取消或供应商失败都不能回退为空白。
        if job['kind'] in {'turn','queue'}:self._promote(chat)
        operation=uuid4().hex;job={**job,'chat_id':chat['id'],'operation_id':operation}
        chat['pending_task']=job;chat['status']='queued';chat['result']=None;self.changed(chat)
        project_id=chat['project_id'];self.project_jobs.setdefault(project_id,deque()).append(job)
        if project_id not in self.drainers or self.drainers[project_id].done():
            self.drainers[project_id]=asyncio.create_task(self._drain(project_id),name='webui-project-'+project_id)
        return {'accepted':True,'operation_id':operation,'chat':dict(chat)}

    async def _drain(self,project_id):
        if not hasattr(self,'foreground_slots'):self.foreground_slots=asyncio.Semaphore(4)
        jobs=self.project_jobs[project_id]
        while jobs and not self.closing:
            job=jobs.popleft();chat=self.chats.get(job['chat_id'])
            if not chat or chat.get('archived') or chat['status']!='queued' or chat.get('pending_task',{}).get('operation_id')!=job['operation_id']:continue
            async with self.foreground_slots:
                chat=self.chats.get(job['chat_id'])
                if self.closing or not chat or chat.get('archived') or chat['status']!='queued' or chat.get('pending_task',{}).get('operation_id')!=job['operation_id']:continue
                chat['status']='running';chat.pop('pending_task',None);self.changed(chat)
                try:
                    owner=await self._owner(chat['id'])
                    owner.task=asyncio.create_task(self._run(chat,owner,job),name='webui-turn-'+chat['id'])
                    await owner.task
                except asyncio.CancelledError:
                    chat['status']='cancelled';self.changed(chat)
                except Exception as exc:
                    log.exception('项目任务失败 %s',chat['id'])
                    chat['status']='busy' if isinstance(exc,SessionBusyError) else 'failed'
                    chat['pending_task']=job
                    chat['result']={'status':'failed','text':'','error_text':str(exc)};self.changed(chat)

    async def _run(self,chat,owner,job):
        agent=owner.agent
        try:
            if owner.config_pending:await self._apply_owner_config(chat,owner)
            if job['kind']=='compact':
                await agent.compact_context();chat['status']='completed'
            else:
                if job['kind']=='queue':
                    agent.resume_queue();stream=agent.run_next_queued_turn()
                else:
                    stream=agent.run_user_turn(job['prompt'])
                async with aclosing(stream):
                    async for _ in stream:pass
                result=agent.last_result
                chat['result']=result.to_dict() if result else None
                chat['status']=result.status if result else 'failed'
        except asyncio.CancelledError:
            chat['status']='cancelled';chat['result']=agent.last_result.to_dict() if agent.last_result else {'status':'cancelled','text':''}
        except Exception as exc:
            chat['status']='failed';chat['result']={'status':'failed','text':'','error_text':str(exc)}
            log.exception('对话运行失败 %s',chat['id'])
        finally:
            owner.permissions.clear();owner.access_at=time.monotonic()
            chat['sdk_session_id']=agent.session_id or chat.get('sdk_session_id');chat['queue_paused']=owner.manual_pause or agent.queue_paused
            self._collect_usage(chat,owner,json_value(agent.state))
            if agent.session_id:
                try:agent.rename_session(agent.session_id,chat['title'])
                except Exception:log.exception('保存对话标题失败 %s',chat['id'])
            if owner.config_pending:
                try:await self._apply_owner_config(chat,owner)
                except Exception as exc:chat['config_apply_error']=str(exc)
            self.changed(chat)
            self.emit({'kind':'host_result','result':chat.get('result')},chat=chat)
            continue_queue=owner.dispatch_next or owner.queue_before_config
            owner.dispatch_next=False;owner.queue_before_config=False
            if continue_queue and chat['status']=='completed' and not self.closing and not owner.manual_pause and not owner.config_pending:
                if agent.pending_inputs:await self._schedule(chat,{'kind':'queue'})
                else:agent.resume_queue();chat['queue_paused']=False;self.changed(chat)

    async def stop(self,chat_id,scope='turn'):
        chat=self.get_chat(chat_id);owner=self.owners.get(chat_id)
        if chat['status']=='queued':
            chat['status']='cancelled';self.changed(chat)
        if owner:
            owner.dispatch_next=False;owner.queue_before_config=False;owner.manual_pause=True
            if self._active(chat_id):
                chat['status']='stopping';self.changed(chat)
                await owner.agent.stop_and_wait();await asyncio.gather(owner.task,return_exceptions=True)
            if scope=='session' and owner.agent.session_id:await owner.agent.stop_session()
        return dict(chat)

    async def release(self,chat_id,force=False):
        lock=self.owner_locks.setdefault(chat_id,asyncio.Lock())
        async with lock:
            owner=self.owners.get(chat_id)
            if not owner:return {'released':True}
            if not force and (self._active(chat_id) or self.get_chat(chat_id)['status']=='queued' or self._process_count(chat_id)):
                raise WebError('任务或后台进程尚未停止，无法释放对话。',409)
            chat=self.get_chat(chat_id);self._collect_usage(chat,owner,json_value(owner.agent.state))
            await owner.agent.close();self.owners.pop(chat_id,None);self.changed(chat)
            return {'released':True}

    async def action(self,chat_id,action,payload=None):
        payload=payload or {};chat=self.get_chat(chat_id)
        if action=='queue_add' and chat.get('draft'):
            if payload.get('delivery','follow_up') not in {'follow_up','steer'}:raise WebError('输入队列类型无效。')
            return await self.submit(chat_id,payload.get('text',payload.get('prompt','')))
        if action=='release':return await self.release(chat_id)
        owner=await self._owner(chat_id);agent=owner.agent
        busy=self._active(chat_id) or chat['status']=='queued'
        idle_actions={'phase','access','model','effort','plan_execute','skills_reload','skills_enable','skills_disable',
                      'skills_unload','mcp_refresh','mcp_reconnect','mcp_reload'}
        if action in idle_actions and busy:raise WebError('当前对话正在运行或排队，操作草稿已保留。',409)
        result={}
        if action=='phase':agent.set_phase(payload['phase']);chat['phase']=agent.work_phase
        elif action=='access':agent.set_execution_access(payload.get('access',payload.get('execution_access')));chat['access']=agent.execution_access
        elif action=='model':agent.switch_model(payload['model_ref']);chat['model_ref']=agent.model_ref
        elif action=='effort':agent.set_effort(payload.get('effort'));chat['reasoning_effort']=agent.reasoning_effort
        elif action=='compact':
            if busy:raise WebError('当前对话忙碌，暂时无法压缩。',409)
            return await self._schedule(chat,{'kind':'compact'})
        elif action=='plan_execute':
            if not chat.get('sdk_session_id'):raise WebError('尚无可执行计划。',409)
            prompt=agent.prepare_plan_execution(chat['sdk_session_id'],payload['digest'])
            return await self.submit(chat_id,prompt)
        elif action=='queue_add':
            item=agent.enqueue_input(payload.get('text',payload.get('prompt','')),payload.get('delivery','follow_up'))
            if item.delivery=='follow_up' and (owner.config_pending or owner.manual_pause):
                if owner.config_pending:owner.queue_before_config=True
                agent.pause_queue()
            result={'item':json_value(item)}
        elif action=='queue_update':result={'item':json_value(agent.update_pending_input(payload['id'],payload['text']))}
        elif action=='queue_remove':agent.remove_pending_input(payload['id'])
        elif action=='queue_convert':result={'item':json_value(agent.convert_pending_input(payload['id'],payload['delivery']))}
        elif action=='queue_pause':
            owner.manual_pause=True;owner.dispatch_next=False;agent.pause_queue();chat['queue_paused']=True
            if chat['status']=='queued' and chat.get('pending_task',{}).get('kind')=='queue':chat['status']='cancelled'
        elif action=='queue_resume':
            if busy:raise WebError('当前对话仍在运行。',409)
            owner.manual_pause=False
            pending=chat.get('pending_task')
            if pending:return await self._schedule(chat,{key:value for key,value in pending.items() if key not in {'operation_id','chat_id'}})
            if agent.pending_inputs:return await self._schedule(chat,{'kind':'queue'})
            agent.resume_queue();chat['queue_paused']=False
        elif action=='skills_list':result={'skills':agent.capabilities.list_skills()}
        elif action=='skills_show':result={'text':agent.capabilities.show_skill(payload['name'])}
        elif action=='skills_reload':result={'text':agent.capabilities.reload_skills()}
        elif action in {'skills_enable','skills_disable'}:result={'text':agent.capabilities.set_skill_enabled(payload['name'],action=='skills_enable')}
        elif action=='skills_unload':result={'text':agent.capabilities.unload_skill(payload['name'])}
        elif action in {'mcp_status','mcp_list'}:result={'mcp':agent.capabilities.mcp_status()}
        elif action=='mcp_refresh':result={'text':await agent.capabilities.refresh_mcp(payload.get('name'))}
        elif action=='mcp_reconnect':result={'text':await agent.capabilities.reconnect_mcp(payload['name'])}
        elif action=='mcp_reload':
            if self.user_home.resolve()!=Path.home().resolve():
                await self.release(chat_id);owner=await self._owner(chat_id);await owner.agent.ready()
                result={'text':'指定用户目录的 MCP 配置已重新装配。'}
            else:result={'text':await agent.capabilities.reload_mcp()}
        elif action in {'process_read','process_show'}:
            result=agent.read_process_output(payload['process_id'],int(payload.get('cursor',0)),min(64000,int(payload.get('max_chars',16000))))
        elif action in {'process_write','process_input'}:
            await agent.write_process_input(payload['process_id'],payload['text']);result={'written':True}
        elif action=='process_background':result={'process':json_value(await agent.background_process(payload['process_id']))}
        elif action=='process_stop':result={'process':json_value(await agent.stop_process(payload['process_id']))}
        elif action=='process_list':result={'processes':agent.list_processes()}
        else:raise WebError('不支持的操作：'+action)
        self.changed(chat);return json_value({**result,'chat':dict(chat)})

    def resolve(self,chat_id,request_id,outcome):
        chat=self.get_chat(chat_id);owner=self.owners.get(chat_id)
        if not owner or request_id not in owner.permissions:raise WebError('审批已经结束或不属于当前对话。',409)
        request=owner.permissions[request_id]
        if outcome=='allow_session' and not request.get('directory_grants'):raise WebError('该请求仅支持本次批准。')
        if not owner.agent.resolve_permission_request(PermissionResolution(request_id,outcome)):raise WebError('审批已失效。',409)
        owner.permissions.pop(request_id,None);self.changed(chat);return {'resolved':True}

    async def settings_snapshot(self,project_id=None):
        root=self.project_root(project_id) if project_id else None
        snapshot=self.configuration.snapshot(root)
        return {**snapshot,'preferences':self.preferences}

    async def save_settings(self,payload):
        if payload.get('domain')=='web':
            data=payload.get('data',{})
            if data.get('theme',self.preferences['theme']) not in {'system','dark','light'}:raise WebError('主题值无效。')
            for key in ('theme','reduce_transparency','reduce_motion','sidebar_width','inspector_width'):
                if key in data:self.preferences[key]=data[key]
            self.store.put('preferences','web',self.preferences)
            self.emit({'kind':'preferences_updated','preferences':self.preferences})
            return {'saved':True,'applied':True,'pending':[],'preferences':self.preferences}
        root=self.project_root(payload['project_id']) if payload.get('project_id') else None
        saved=self.configuration.save(payload,root)
        domain=payload.get('domain')
        if domain=='ui':
            self.emit({'kind':'ui_updated','ui':json_value(self._config().ui)})
            return {**saved,'saved':True,'applied':True,'pending':[]}
        if domain=='execution':
            self.emit({'kind':'config_updated','domain':domain,'restart_required':True})
            return {**saved,'saved':True,'applied':False,'pending':[],'restart_required':True}
        pending=[];applied=[]
        for chat_id,owner in tuple(self.owners.items()):
            chat=self.chats.get(chat_id)
            if not chat:continue
            if payload.get('scope')=='project' and chat['project_id']!=payload.get('project_id'):continue
            owner.pending_domains.add(domain)
            if self._active(chat_id):
                owner.config_pending=True;chat['pending_config']=True
                if not owner.agent.queue_paused:
                    owner.queue_before_config=True;owner.agent.pause_queue()
                pending.append(chat_id);self.changed(chat)
            else:
                try:await self._apply_owner_config(chat,owner);applied.append(chat_id)
                except Exception as exc:
                    owner.config_pending=True;chat['pending_config']=True;chat['config_apply_error']=str(exc);pending.append(chat_id);self.changed(chat)
        self.emit({'kind':'config_updated','applied':applied,'pending':pending,'domain':payload.get('domain')})
        return {**saved,'saved':True,'applied':applied,'pending':pending,'restart_required':payload.get('domain')=='execution'}

    async def _apply_owner_config(self,chat,owner):
        agent=owner.agent;domains=owner.pending_domains or {'models','runtime','rules','mcp'}
        if domains & {'models','runtime'}:
            config=self._config().to_agent_config()
            if hasattr(self,'execution_configs') and chat['project_id'] in self.execution_configs:
                from copy import deepcopy
                config.execution=deepcopy(self.execution_configs[chat['project_id']])
            agent.reload_models(config)
            if 'runtime' in domains:
                runtime=config.runtime
                runtime.work_phase=agent.work_phase;runtime.execution_access=agent.execution_access
                agent.apply_runtime_settings(runtime)
        if 'rules' in domains:
            storage=self.configuration.make_permission_storage(self.project_root(chat['project_id']))
            for scope in ('user','project'):
                agent.permission_storage.replace_rules(scope,storage.rules_for_scope(scope),persist=False)
        if 'mcp' in domains and self.enable_mcp:
            if self.user_home.resolve()==Path.home().resolve():
                await agent.capabilities.reload_mcp()
            else:
                # 测试用户目录不能回退到真实用户的 MCP 来源。
                if self._process_count(chat['id']):raise WebError('后台进程结束后应用 MCP 配置。',409)
                await self.release(chat['id'],force=True);replacement=await self._owner(chat['id'])
                await replacement.agent.ready()
        owner.pending_domains.clear();owner.config_pending=False;chat['pending_config']=False
        chat.pop('config_apply_error',None);self.changed(chat)

    async def events_after(self,after=0):
        if not self.store.cursor_valid(after):
            yield {'kind':'reset_required','sequence':self.store.watermark,'reason':'重放窗口已失效，请重新读取快照。'}
            after=self.store.watermark
        while not self.closing:
            signal=self.signal;events=self.store.events_after(after)
            for event in events:after=event['sequence'];yield event
            if len(events)==500:continue
            try:await asyncio.wait_for(signal.wait(),12)
            except TimeoutError:yield None

    async def _maintain(self):
        try:
            while not self.closing:
                await asyncio.sleep(2)
                for chat_id,owner in tuple(self.owners.items()):
                    try:
                        processes=json_value(owner.agent.list_processes())
                        signature=json.dumps(processes,sort_keys=True)
                        if signature!=owner.process_signature:
                            owner.process_signature=signature
                            chat=self.chats.get(chat_id)
                            if chat:self.emit({'kind':'processes_updated','processes':processes},chat=chat)
                        if not self._active(chat_id) and self.get_chat(chat_id)['status']!='queued' and not self._process_count(chat_id) and time.monotonic()-owner.access_at>30:
                            await self.release(chat_id)
                    except Exception:log.exception('维护对话运行状态失败 %s',chat_id)
        except asyncio.CancelledError:pass

    async def close(self):
        if self.closed:return
        self.closing=True;self.signal.set()
        if self.maintenance:self.maintenance.cancel();await asyncio.gather(self.maintenance,return_exceptions=True)
        for chat_id in tuple(self.owners):
            try:
                await self.stop(chat_id,'session');await self.release(chat_id,force=True)
            except Exception:log.exception('对话收尾失败 %s',chat_id)
        for task in self.drainers.values():
            if not task.done():task.cancel()
        await asyncio.gather(*self.drainers.values(),return_exceptions=True)
        self.store.close();self.closed=True

    async def shutdown(self):
        await self.close()
        if self.shutdown_callback:self.shutdown_callback()
        return {'closed':True}
