"""只监听本机的 Web 传输层。"""
from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from fastapi import FastAPI, Query, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .manager import LabError, LabManager
from .docs import render_api_docs


class CreateSession(BaseModel):
    model_config = ConfigDict(extra='forbid')
    title: str = Field(default='', max_length=100)
    mode: Literal['demo', 'live'] = 'demo'
    model: str | None = Field(default=None, max_length=150)


class Prompt(BaseModel):
    model_config = ConfigDict(extra='forbid')
    prompt: str = Field(min_length=1, max_length=20_000)

    @field_validator('prompt')
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError('任务不能为空')
        return value


class Resolution(BaseModel):
    model_config = ConfigDict(extra='forbid')
    outcome: Literal['allow', 'deny']


def create_app(root: Path | None = None) -> FastAPI:
    root = (root or Path(os.environ.get('LANCHER_LAB_ROOT', Path(__file__).resolve().parent.parent))).resolve()

    @asynccontextmanager
    async def lifespan(app):
        manager = LabManager(root)
        app.state.manager = manager
        await manager.start()
        try:
            yield
        finally:
            await manager.close()

    app = FastAPI(title='LanCher Agent Lab', version='0.1.0', lifespan=lifespan, docs_url=None, redoc_url=None)

    @app.exception_handler(LabError)
    async def lab_error(_request, error):
        return JSONResponse({'detail': str(error)}, status_code=error.status)

    @app.middleware('http')
    async def local_only(request: Request, call_next):
        # 本机浏览器可以操作文件，拒绝其他站点借浏览器向本地服务发指令。
        host = request.url.hostname
        if host not in {'127.0.0.1', 'localhost', '::1', 'testserver'}:
            return JSONResponse({'detail': '仅允许本机访问。'}, status_code=403)
        origin = request.headers.get('origin')
        if origin and origin != str(request.base_url).rstrip('/'):
            return JSONResponse({'detail': '来源不匹配。'}, status_code=403)
        if request.headers.get('sec-fetch-site') == 'cross-site':
            return JSONResponse({'detail': '拒绝跨站请求。'}, status_code=403)
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'"
        return response

    @app.get('/docs', include_in_schema=False)
    async def docs():
        return HTMLResponse(render_api_docs(app.openapi()))

    @app.get('/api/status')
    async def status(request: Request):
        return request.app.state.manager.status()

    @app.get('/api/sessions')
    async def sessions(request: Request):
        manager = request.app.state.manager
        return [manager.summary(item) for item in sorted(manager.sessions.values(), key=lambda row: row.created_at, reverse=True)]

    @app.post('/api/sessions', status_code=201)
    async def create_session(body: CreateSession, request: Request):
        manager = request.app.state.manager
        return manager.summary(await manager.create(title=body.title, mode=body.mode, model=body.model))

    @app.get('/api/sessions/{session_id}')
    async def session_detail(session_id: str, request: Request):
        manager = request.app.state.manager
        return manager.detail(manager.get(session_id))

    @app.post('/api/sessions/{session_id}/turns', status_code=202)
    async def submit(session_id: str, body: Prompt, request: Request):
        manager = request.app.state.manager
        session = manager.get(session_id)
        await manager.submit(session, body.prompt)
        return manager.summary(session)

    @app.post('/api/sessions/{session_id}/stop')
    async def stop(session_id: str, request: Request):
        manager = request.app.state.manager
        return await manager.stop(manager.get(session_id))

    @app.post('/api/sessions/{session_id}/permissions/{request_id}')
    async def resolve(session_id: str, request_id: str, body: Resolution, request: Request):
        manager = request.app.state.manager
        manager.resolve(manager.get(session_id), request_id, body.outcome)
        return {'resolved': True}

    @app.post('/api/sessions/{session_id}/queue', status_code=202)
    async def queue(session_id: str, body: Prompt, request: Request):
        manager = request.app.state.manager
        return await manager.enqueue(manager.get(session_id), body.prompt)

    @app.post('/api/sessions/{session_id}/resume')
    async def resume(session_id: str, request: Request):
        manager = request.app.state.manager
        return await manager.resume(manager.get(session_id))

    @app.get('/api/sessions/{session_id}/events')
    async def events(session_id: str, request: Request, after: int = Query(default=0, ge=0)):
        manager = request.app.state.manager
        session = manager.get(session_id)
        last_event_id = request.headers.get('last-event-id', '')
        if last_event_id.isdigit():
            after = max(after, int(last_event_id))
        async def stream():
            yield ': connected\n\n'
            async for event in manager.events_after(session, after):
                if await request.is_disconnected():
                    break
                if event is None:
                    yield ': heartbeat\n\n'
                else:
                    yield f"id: {event['sequence']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
        return StreamingResponse(stream(), media_type='text/event-stream',
                                 headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})

    @app.get('/api/sessions/{session_id}/files')
    async def files(session_id: str, request: Request):
        manager = request.app.state.manager
        return {'files': manager.files(manager.get(session_id))}

    @app.get('/api/sessions/{session_id}/file')
    async def file(session_id: str, request: Request, path: str = Query(min_length=1, max_length=300)):
        manager = request.app.state.manager
        return manager.file(manager.get(session_id), path)

    @app.get('/')
    async def index():
        return FileResponse(root / 'web' / 'index.html')

    app.mount('/assets', StaticFiles(directory=root / 'web', check_dir=False), name='assets')
    return app


app = create_app()

