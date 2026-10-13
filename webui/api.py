"""本机 HTTP 传输层；所有业务动作由宿主和 SDK 执行。"""
from __future__ import annotations
import asyncio
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI,Query,Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse,JSONResponse,StreamingResponse,HTMLResponse,Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel,ConfigDict,Field,field_validator

from .manager import AppManager,WebError
from .commands import complete,execute,definitions
from .files import list_files,read_file
from .native_dialog import pick_directory
from .discovery import DiscoveryService


class Body(BaseModel):
    model_config=ConfigDict(extra='forbid')

class ProjectBody(Body):
    path:str=Field(min_length=1,max_length=1000)
    name:str|None=Field(default=None,max_length=100)

class ChatBody(Body):
    project_id:str
    title:str=Field(default='',max_length=150)
    model_ref:str|None=None
    draft_id:str|None=Field(default=None,pattern=r'^[0-9a-fA-F]{32}$')
    phase:Literal['discuss','plan','execute']|None=None
    access:Literal['project','full']|None=None
    reasoning_effort:str|None=Field(default=None,min_length=1,max_length=64)

class DiscoveryBody(Body):
    provider_id:str=Field(min_length=1,max_length=150)
    provider:dict
    revision:str=Field(min_length=1,max_length=128)
    project_id:str|None=None
    refresh:bool=False

class DiscoveryMergeBody(Body):
    provider_id:str=Field(min_length=1,max_length=150)
    provider:dict
    revision:str=Field(min_length=1,max_length=128)
    project_id:str|None=None
    discovery_id:str=Field(pattern=r'^[0-9a-f]{32}$')
    selected_ids:list[str]=Field(max_length=10000)

class TurnBody(Body):
    prompt:str=Field(min_length=1,max_length=20000)
    attachments:list[str]=Field(default_factory=list,max_length=20)
    @field_validator('prompt')
    @classmethod
    def nonblank(cls,value):
        if not value.strip():raise ValueError('输入不能为空。')
        return value

class StopBody(Body):
    scope:Literal['turn','session']='turn'

class PermissionBody(Body):
    outcome:Literal['allow_once','allow_session','deny']

class CommandBody(Body):
    text:str=Field(min_length=1,max_length=20000)
    confirmed:bool=False


def create_app(root:Path|None=None,user_home:Path|None=None,provider_factory=None,enable_mcp=True,*,runtime_root:Path|None=None,desktop:bool=False,desktop_state:dict|None=None):
    root=Path(root or os.environ.get('LANCHER_WEBUI_ROOT',Path(__file__).resolve().parent.parent)).resolve()

    @asynccontextmanager
    async def lifespan(app):
        manager=AppManager(runtime_root or root,user_home=user_home,provider_factory=provider_factory,enable_mcp=enable_mcp,resource_root=root)
        manager.shutdown_callback=getattr(app.state,'shutdown_callback',None)
        app.state.manager=manager
        app.state.discovery=DiscoveryService(manager.configuration)
        await manager.start()
        try:yield
        finally:await manager.close()

    app=FastAPI(title='LanCher Code WebUI',version='0.2.0',lifespan=lifespan,docs_url=None,redoc_url=None)

    @app.middleware('http')
    async def security(request,call_next):
        allowed={'127.0.0.1','localhost','::1'}
        if user_home is not None:allowed.add('testserver')
        if request.url.hostname not in allowed:return JSONResponse({'detail':'仅允许本机访问。'},403)
        origin=request.headers.get('origin')
        if origin and origin!=str(request.base_url).rstrip('/'):
            return JSONResponse({'detail':'请求来源不匹配。'},403)
        if request.headers.get('sec-fetch-site')=='cross-site':
            return JSONResponse({'detail':'拒绝跨站操作。'},403)
        response=await call_next(request)
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['Referrer-Policy']='no-referrer'
        response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'"
        return response

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request,exc):
        # Pydantic 默认错误包含完整 input；含凭据的设置正文不能被错误回显。
        domain='models' if '/settings/model-discovery' in request.url.path else 'request'
        labels={'missing':'请填写该必填项。','extra_forbidden':'该字段不属于当前请求。'}
        issues=[{'domain':domain,'path':[part for part in row.get('loc',()) if isinstance(part,(str,int)) and part not in {'body'}],
                 'message':labels.get(row.get('type'),'该字段格式无效，请检查类型或选项。')} for row in exc.errors()]
        return JSONResponse({'detail':'请求参数格式无效，请检查标出的字段。','issues':issues},status_code=422)

    @app.exception_handler(WebError)
    @app.exception_handler(Exception)
    async def errors(request,exc):
        status=getattr(exc,'status',None)
        if status is None:
            from lancher_code.errors import ConfigError
            from lancher_code.sessions.storage import SessionBusyError,SessionRepositoryError
            status=409 if isinstance(exc,(ConfigError,SessionBusyError,SessionRepositoryError)) else (400 if isinstance(exc,(ValueError,KeyError)) else 500)
        if status==500:
            import logging
            logging.getLogger(__name__).exception('API 操作失败',exc_info=exc)
        from lancher_code.logging_system import sanitize_log_text
        body={'detail':sanitize_log_text(str(exc))}
        if getattr(exc,'issues',None):body['issues']=exc.issues
        return JSONResponse(body,status_code=status)

    def manager(request):return request.app.state.manager

    @app.get('/api/bootstrap')
    async def bootstrap(request:Request):return await manager(request).bootstrap()

    @app.get('/api/status')
    async def status(request:Request):
        m=manager(request)
        return {'name':'LanCher Code WebUI','sdk_commit':m.sdk_snapshot['commit'],'pid':os.getpid(),
                'root':str(root),'watermark':m.store.watermark,'execution':'native'}

    @app.post('/api/projects',status_code=201)
    async def project(body:ProjectBody,request:Request):return await manager(request).add_project(body.path,body.name)

    @app.post('/api/projects/pick')
    async def pick(request:Request):
        picker=getattr(request.app.state,'directory_picker',None)
        return await asyncio.to_thread(picker) if picker else await pick_directory()

    @app.patch('/api/projects/{project_id}')
    async def patch_project(project_id:str,body:dict,request:Request):return await manager(request).patch_project(project_id,body)

    @app.get('/api/projects/{project_id}/impact')
    async def project_impact(project_id:str,request:Request):return manager(request).project_impact(project_id)

    @app.delete('/api/projects/{project_id}')
    async def remove_project(project_id:str,request:Request,confirmed:bool=False):return await manager(request).remove_project(project_id,confirmed)

    @app.get('/api/projects/{project_id}/files')
    async def files(project_id:str,request:Request,q:str='',chat_id:str|None=None,scope:Literal['files','changes']='files'):
        return manager(request).project_files(project_id,q,chat_id,scope)

    @app.get('/api/projects/{project_id}/file')
    async def project_file(project_id:str,request:Request,path:str):
        return manager(request).preview_project_file(project_id,path)

    @app.post('/api/chats',status_code=201)
    async def chat(body:ChatBody,request:Request):return await manager(request).create_chat(body.project_id,body.title,body.model_ref,draft_id=body.draft_id,phase=body.phase,access=body.access,reasoning_effort=body.reasoning_effort)

    @app.get('/api/chats/{chat_id}')
    async def detail(chat_id:str,request:Request,before:int|None=Query(None,ge=0),limit:int=Query(50,ge=1,le=100)):
        return await manager(request).chat_detail(chat_id,before,limit)

    @app.patch('/api/chats/{chat_id}')
    async def patch(chat_id:str,body:dict,request:Request):return await manager(request).patch_chat(chat_id,body)

    @app.delete('/api/chats/{chat_id}')
    async def remove(chat_id:str,request:Request,confirmed:bool=False):return await manager(request).remove_chat(chat_id,confirmed)

    @app.post('/api/chats/{chat_id}/turns',status_code=202)
    async def turn(chat_id:str,body:TurnBody,request:Request):
        m=manager(request)
        if body.prompt.lstrip().startswith('/'):
            result=await execute(m,chat_id,body.prompt)
            if result.get('prompt'):
                submitted=await m.submit(chat_id,result.pop('prompt'),body.attachments)
                return {**result,**submitted}
            return result
        return await m.submit(chat_id,body.prompt,body.attachments)

    @app.post('/api/chats/{chat_id}/stop')
    async def stop(chat_id:str,body:StopBody,request:Request):return await manager(request).stop(chat_id,body.scope)

    @app.post('/api/chats/{chat_id}/permissions/{request_id}')
    async def permission(chat_id:str,request_id:str,body:PermissionBody,request:Request):
        return manager(request).resolve(chat_id,request_id,body.outcome)

    @app.post('/api/chats/{chat_id}/actions')
    async def action(chat_id:str,body:dict,request:Request):
        action=body.get('action')
        if not isinstance(action,str):raise WebError('缺少 action。')
        return await manager(request).action(chat_id,action,{key:value for key,value in body.items() if key!='action'})

    @app.get('/api/chats/{chat_id}/file')
    async def file(chat_id:str,request:Request,path:str=Query(min_length=1,max_length=1000)):
        m=manager(request);chat=m.get_chat(chat_id)
        return m.preview_file(chat_id,path)

    @app.get('/api/commands')
    async def commands():return definitions()

    @app.get('/api/commands/complete')
    async def completion(request:Request,chat_id:str,text:str=''):
        return await complete(manager(request),chat_id,text)

    @app.post('/api/chats/{chat_id}/commands')
    async def command(chat_id:str,body:CommandBody,request:Request):
        m=manager(request);result=await execute(m,chat_id,body.text,body.confirmed)
        if result.get('prompt'):
            submitted=await m.submit(chat_id,result.pop('prompt'))
            return {**result,**submitted}
        return result

    @app.get('/api/settings')
    async def settings(request:Request,project_id:str|None=None,domain:str|None=None):return await manager(request).settings_snapshot(project_id,domain)

    @app.patch('/api/settings')
    async def save(body:dict,request:Request):return await manager(request).save_settings(body)

    def discovery_project(request:Request,project_id:str|None):
        return Path(manager(request).get_project(project_id)['path']) if project_id else None

    @app.post('/api/settings/model-discovery')
    async def discover_models(body:DiscoveryBody,request:Request):
        return await request.app.state.discovery.discover(body.model_dump(),discovery_project(request,body.project_id))

    @app.post('/api/settings/model-discovery/merge')
    async def merge_models(body:DiscoveryMergeBody,request:Request):
        return request.app.state.discovery.merge(body.model_dump(),discovery_project(request,body.project_id))

    @app.get('/api/events')
    async def events(request:Request,after:int=Query(0,ge=0)):
        m=manager(request);header=request.headers.get('last-event-id','')
        if header.isdigit():after=max(after,int(header))
        async def stream():
            yield ': connected\n\n'
            async for event in m.events_after(after):
                if await request.is_disconnected():break
                if event is None:yield ': heartbeat\n\n'
                else:yield f"id: {event['sequence']}\ndata: {json.dumps(event,ensure_ascii=False)}\n\n"
        return StreamingResponse(stream(),media_type='text/event-stream',headers={'Cache-Control':'no-cache','X-Accel-Buffering':'no'})

    @app.post('/api/shutdown')
    async def shutdown(request:Request):return await manager(request).shutdown()

    @app.get('/favicon.ico')
    async def native_favicon():return FileResponse(root/'frontend/dist/favicon.ico',media_type='image/x-icon')

    @app.get('/favicon.svg')
    async def favicon():return FileResponse(root/'frontend/dist/favicon.svg',media_type='image/svg+xml')

    @app.get('/docs',response_class=HTMLResponse)
    async def docs():
        from html import escape
        rows=''.join('<tr><td>'+escape(', '.join(sorted(getattr(route,'methods',[]) or [])))+'</td><td><code>'+escape(route.path)+'</code></td></tr>'
                     for route in app.routes if route.path.startswith('/api/'))
        return '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>LanCher Code WebUI API</title><style>body{font:16px system-ui;margin:48px;color:#222}td{padding:9px 24px 9px 0;border-bottom:1px solid #ddd}a{color:#2464d0}</style><h1>LanCher Code WebUI API</h1><p>本机单 worker · 原生 SDK 工具 · <a href="/openapi.json">完整 OpenAPI JSON</a> · <a href="/">返回工作台</a></p><table>'+rows+'</table></html>'

    if desktop:
        @app.get('/desktop-host.js')
        async def desktop_host():
            return Response('window.__LANCHER_DESKTOP__=true;window.__LANCHER_UI_STATE__='+json.dumps(desktop_state or {},ensure_ascii=False)+';',media_type='application/javascript',headers={'Cache-Control':'no-store'})

    @app.get('/')
    async def index():
        path=root/'frontend/dist/index.html'
        if not path.is_file():return JSONResponse({'detail':'前端尚未构建，请运行 setup.ps1。'},503)
        if desktop:
            return HTMLResponse(path.read_text(encoding="utf-8").replace("</head>",'<script src="/desktop-host.js"></script></head>'))
        return FileResponse(path)

    app.mount('/assets',StaticFiles(directory=root/'frontend/dist/assets',check_dir=False),name='assets')
    return app


app=create_app()
