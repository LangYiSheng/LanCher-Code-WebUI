"""前端只获得窗口操作；所有 Agent 操作仍走现有后端。"""
from __future__ import annotations
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import tempfile
from urllib.parse import urlsplit

class DesktopBridge:
    def __init__(self,server):
        self._server=server
        self._window=None
        self._exiting=False
        self._maximized=False
        self._tray=None
        self._callbacks=[]
        self._frame=None

    def _authorize(self):
        if not self._window:raise RuntimeError('窗口尚未就绪。')
        url=urlsplit(self._window.get_current_url() or '')
        if url.scheme!='http' or url.hostname!='127.0.0.1' or url.port!=self._server.port:
            raise PermissionError('窗口已离开工作台，拒绝宿主操作。')

    def window_state(self):
        self._authorize()
        return {'maximized':self._maximized}

    def minimize(self):
        self._authorize();self._window.minimize()

    def toggle_maximize(self):
        self._authorize()
        next_state=not self._maximized
        if self._maximized:self._window.restore()
        else:self._window.maximize()
        self._maximized=next_state
        return {'maximized':self._maximized}

    def _native_move(self,command):
        from System import Action
        def start_move():
            user=ctypes.WinDLL('user32',use_last_error=True)
            user.SendMessageW.argtypes=[wintypes.HWND,wintypes.UINT,wintypes.WPARAM,wintypes.LPARAM]
            user.SendMessageW.restype=wintypes.LPARAM
            # WebView2 的鼠标捕获属于 UI 线程，释放与移动也必须在该线程执行。
            user.ReleaseCapture()
            hwnd=int(self._window.native.Handle.ToInt64())
            user.SendMessageW(hwnd,0x0112,command,0)
        self._window.native.Invoke(Action(start_move))

    def drag(self):
        self._authorize()
        self._native_move(0xF010|2)

    def resize(self,edge):
        self._authorize()
        direction={'w':1,'e':2,'n':3,'nw':4,'ne':5,'s':6,'sw':7,'se':8}.get(edge)
        if direction is None:raise ValueError('未知窗口边缘。')
        if not self._maximized:self._native_move(0xF000|direction)

    def close_status(self):
        self._authorize();return self._server.activity() if self._server.thread.is_alive() else {'tasks':0,'processes':0}

    def quit(self):
        self._authorize();self._quit()

    def _quit(self):
        self._server.stop()
        self._exiting=True
        if self._tray:self._dispose_tray()
        self._window.destroy()

    def hide(self):
        self._authorize()
        if not self._tray:raise RuntimeError('托盘尚未就绪，窗口已保留。')
        self._window.hide()

    def _show(self):
        self._window.show()
        self._window.restore()

    def _state_changed(self,maximized):
        self._maximized=maximized
        try:self._window.evaluate_js("window.dispatchEvent(new Event('lancher-window-state'))")
        except Exception:pass

    def _request_close(self):
        if self._exiting:return True
        if not self._window.events.loaded.is_set():
            self._server.stop();return True
        self._window.evaluate_js("window.dispatchEvent(new Event('lancher-close-requested'))")
        return False

    def _setup_tray(self,icon_path):
        from System import Action
        from System.Drawing import Icon, SystemIcons
        from System.Windows.Forms import NotifyIcon,ContextMenuStrip,ToolStripMenuItem
        def setup():
            from .frame import NativeFrame
            self._frame=NativeFrame(int(self._window.native.Handle.ToInt64()))
            self._frame.install()
            tray=NotifyIcon();tray.Text='LanCher Code Desktop'
            tray.Icon=Icon(str(icon_path)) if icon_path.is_file() else SystemIcons.Application
            menu=ContextMenuStrip()
            show=ToolStripMenuItem('打开工作台');leave=ToolStripMenuItem('退出')
            show_callback=lambda sender,args:self._show()
            leave_callback=lambda sender,args:(self._show(),self._request_close())
            self._callbacks=[show_callback,leave_callback]
            show.Click+=show_callback;leave.Click+=leave_callback;tray.DoubleClick+=show_callback
            menu.Items.Add(show);menu.Items.Add(leave);tray.ContextMenuStrip=menu
            tray.Visible=True;self._tray=tray
        self._window.native.Invoke(Action(setup))

    def _dispose_tray(self):
        from System import Action
        def dispose():
            if self._tray:self._tray.Visible=False;self._tray.Dispose();self._tray=None
        self._window.native.Invoke(Action(dispose))

    def _pick_directory(self):
        self._authorize()
        import webview
        from System import Action
        result=[]
        self._window.native.Invoke(Action(lambda:result.append(self._window.create_file_dialog(webview.FileDialog.FOLDER,directory=str(self._server.storage)))))
        selected=result[0]
        if not selected:return {'path':None,'cancelled':True}
        path=Path(selected[0]).resolve()
        if not path.is_dir():raise ValueError('选择的项目目录已失效，请重新选择。')
        return {'path':str(path),'cancelled':False}

    def import_config(self):
        self._authorize()
        async def perform():
            activity=await self._server._activity()
            if activity['tasks'] or activity['processes']:raise RuntimeError('有任务或后台进程时不能导入配置，请先完成或停止。')
            source=Path.home()/'.lancher/lancher.yaml'
            if not source.is_file():return {'imported':False}
            # 先用 SDK 配置适配校验，禁止把损坏源覆盖到桌面副本。
            from webui.configuration import _read_yaml
            from lancher_code.config.loader import load_config_data
            load_config_data(_read_yaml(source))
            target=self._server.home/'.lancher/lancher.yaml'
            descriptor,temporary=tempfile.mkstemp(dir=target.parent,suffix='.tmp')
            try:
                with os.fdopen(descriptor,'wb') as output:output.write(source.read_bytes())
                os.replace(temporary,target)
            finally:Path(temporary).unlink(missing_ok=True)
            manager=self._server.app.state.manager
            for chat_id in tuple(manager.owners):await manager.release(chat_id)
            manager.emit({'kind':'config_updated'})
            return {'imported':True}
        return self._server.call(perform())
