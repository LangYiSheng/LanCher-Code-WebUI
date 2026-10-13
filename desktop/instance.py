"""按桌面数据目录限制单实例；重复启动只唤醒自身窗口。"""
from __future__ import annotations
import ctypes
from ctypes import wintypes
import hashlib
import http.client
import json
import os
import time
from pathlib import Path

class Instance:
    def __init__(self,storage:Path):
        self.path=storage/'desktop-instance.json'
        self.user32=None
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.CreateMutexW.argtypes=[ctypes.c_void_p,wintypes.BOOL,wintypes.LPCWSTR]
        kernel.CreateMutexW.restype=wintypes.HANDLE
        kernel.CloseHandle.argtypes=[wintypes.HANDLE]
        self.kernel=kernel
        name='Local\\LanCherCodeDesktop-'+hashlib.sha256(str(storage.resolve()).casefold().encode()).hexdigest()[:24]
        self.handle=kernel.CreateMutexW(None,False,name)
        if not self.handle:raise ctypes.WinError(ctypes.get_last_error())
        self.primary=ctypes.get_last_error()!=183

    def publish(self,server):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        temporary=self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps({'pid':os.getpid(),'port':server.port,'token':server.token}),encoding='utf-8')
        temporary.replace(self.path)

    def activate(self):
        for _ in range(60):
            connection=None
            try:
                record=json.loads(self.path.read_text(encoding='utf-8'))
                connection=http.client.HTTPConnection('127.0.0.1',record['port'],timeout=2)
                connection.request('POST','/desktop/activate',headers={'x-desktop-token':record['token']})
                response=connection.getresponse();response.read()
                if response.status==200:return True
            except (OSError,ValueError,KeyError,http.client.HTTPException):pass
            finally:
                if connection:connection.close()
            time.sleep(.1)
        return False

    def close(self):
        if self.primary:self.path.unlink(missing_ok=True)
        if self.handle:self.kernel.CloseHandle(self.handle);self.handle=None
