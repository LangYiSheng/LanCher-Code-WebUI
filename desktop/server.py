"""独立端口、用户目录和会话认证，不接管已有浏览器服务。"""
from __future__ import annotations
import asyncio
import hmac
import json
import secrets
import socket
import threading
import time
from pathlib import Path

import uvicorn
from fastapi import Request
from fastapi.responses import JSONResponse, RedirectResponse
from webui.api import create_app

COOKIE = 'lancher_desktop_session'

class DesktopServer:
    def __init__(self, resources: Path, storage: Path, *, enable_mcp=True):
        self.storage=storage
        self.storage.mkdir(parents=True, exist_ok=True)
        self.home=storage/'home'
        (self.home/'.lancher').mkdir(parents=True, exist_ok=True)
        self.ui_path=storage/'ui-state.json'
        try:
            self.ui_state=json.loads(self.ui_path.read_text(encoding='utf-8'))
            if not isinstance(self.ui_state,dict):self.ui_state={}
        except (OSError,ValueError):self.ui_state={}
        self.token=secrets.token_urlsafe(32)
        self.socket=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
        # 不先探测再绑定，端口从这个持续持有的 socket 取得。
        self.socket.bind(('127.0.0.1',0))
        self.port=self.socket.getsockname()[1]
        self.url=f'http://127.0.0.1:{self.port}'
        self.app=create_app(resources,user_home=self.home,runtime_root=storage,desktop=True,enable_mcp=enable_mcp,desktop_state=self.ui_state)
        self.activate=lambda: None
        self.loop=None
        self.error=None
        self.server=uvicorn.Server(uvicorn.Config(self.app,host='127.0.0.1',port=self.port,workers=1,log_level='warning',access_log=False,timeout_graceful_shutdown=30))
        self.app.state.shutdown_callback=lambda:setattr(self.server,'should_exit',True)
        token=self.token
        @self.app.middleware('http')
        async def authorize(request:Request,call_next):
            if request.url.path=='/desktop/start':
                if not hmac.compare_digest(request.query_params.get('token',''),token):
                    return JSONResponse({'detail':'桌面会话无效。'},401)
                response=RedirectResponse('/',status_code=303)
                response.headers['Cache-Control']='no-store'
                response.headers['Referrer-Policy']='no-referrer'
                response.set_cookie(COOKIE,token,httponly=True,samesite='strict')
                return response
            credential=request.cookies.get(COOKIE,'')
            if request.url.path=='/desktop/activate':
                credential=request.headers.get('x-desktop-token','')
            if not hmac.compare_digest(credential,token):
                return JSONResponse({'detail':'需要桌面会话。'},401)
            return await call_next(request)
        @self.app.post('/desktop/activate')
        async def activate():
            self.activate()
            return {'activated':True}
        @self.app.post('/desktop/ui-state')
        async def save_ui_state(request:Request):
            raw=await request.body()
            if len(raw)>2_000_000:return JSONResponse({'detail':'草稿过大，尚未保存。'},413)
            try:
                change=json.loads(raw)
                key=change['key']
                if not isinstance(key,str) or len(key)>300 or 'value' not in change:raise ValueError()
                updated={**self.ui_state,key:change['value']}
                serialized=json.dumps(updated,ensure_ascii=False)
                if len(serialized.encode())>16_000_000:raise ValueError()
            except (ValueError,KeyError,TypeError):return JSONResponse({'detail':'桌面状态格式无效。'},400)
            temporary=self.ui_path.with_suffix('.tmp')
            temporary.write_text(serialized,encoding='utf-8')
            temporary.replace(self.ui_path)
            self.ui_state.clear();self.ui_state.update(updated)
            return {'saved':True}
        self.thread=threading.Thread(target=self._run,name='desktop-backend',daemon=True)

    def _run(self):
        async def serve():
            self.loop=asyncio.get_running_loop()
            await self.server.serve(sockets=[self.socket])
        try:asyncio.run(serve())
        except BaseException as error:self.error=error
        finally:self.socket.close()

    def start(self,timeout=30):
        self.thread.start()
        deadline=time.monotonic()+timeout
        while not self.server.started:
            if self.error:raise RuntimeError('桌面服务启动失败。') from self.error
            if not self.thread.is_alive():raise RuntimeError('桌面服务在就绪前退出。')
            if time.monotonic()>deadline:
                self.server.should_exit=True
                raise TimeoutError('桌面服务启动超时，请检查桌面日志。')
            time.sleep(.05)

    def call(self,coroutine,timeout=30):
        if self.loop is None or not self.thread.is_alive():
            coroutine.close()
            raise RuntimeError('桌面后端未运行。')
        return asyncio.run_coroutine_threadsafe(coroutine,self.loop).result(timeout)

    async def _activity(self):
        manager=self.app.state.manager
        return {'tasks':sum(manager._active(chat_id) or chat.get('status')=='queued' for chat_id,chat in manager.chats.items()),
                'processes':sum(manager._process_count(chat_id) for chat_id in manager.owners)}

    def activity(self):return self.call(self._activity(),10)

    def stop(self):
        if not self.thread.is_alive():return
        self.call(self.app.state.manager.shutdown(),35)
        self.server.should_exit=True
        self.thread.join(timeout=35)
        if self.thread.is_alive():raise TimeoutError('桌面任务仍在收尾，尚未退出。')
