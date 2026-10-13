"""桌面入口，开发与冻结包共用，不调用原仓库或现有 WebUI 服务。"""
from __future__ import annotations
import argparse
import ctypes
import logging
import os
from pathlib import Path
import sys

from .bridge import DesktopBridge
from .instance import Instance
from .server import DesktopServer


def resource_root():
    return Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parent.parent))


def run(resources:Path,storage:Path,*,smoke=None):
    storage.mkdir(parents=True,exist_ok=True)
    instance=Instance(storage)
    server=None
    try:
        if not instance.primary:
            if not instance.activate():raise RuntimeError('已有桌面实例尚未响应，请稍后重试。')
            return
        from lancher_code.logging_system import configure_logging
        configure_logging(log_path=storage/'data/sdk-errors.log')
        import webview
        server=DesktopServer(resources,storage)
        server.start()
        bridge=DesktopBridge(server)
        window=webview.create_window('LanCher Code Desktop',server.url+'/desktop/start?token='+server.token,
            js_api=bridge,width=1320,height=900,min_size=(820,560),frameless=True,easy_drag=False,
            shadow=True,resizable=True,text_select=True,zoomable=True,background_color='#f3f3f3')
        bridge._window=window
        server.app.state.directory_picker=bridge._pick_directory
        server.activate=bridge._show
        window.events.closing+=bridge._request_close
        window.events.maximized+=lambda:bridge._state_changed(True)
        window.events.restored+=lambda:bridge._state_changed(False)
        window.events.shown+=lambda:bridge._setup_tray(resources/'frontend/dist/favicon.ico')
        instance.publish(server)
        # 只允许当前本机工作台；外部文档链接交给系统浏览器。
        def guard():
            from urllib.parse import urlsplit
            current=window.get_current_url() or ''
            parsed=urlsplit(current)
            if parsed.hostname!='127.0.0.1' or parsed.port!=server.port:
                window.load_url(server.url)
        window.events.loaded+=guard
        if smoke:window.events.loaded+=lambda:smoke(window,bridge,server)
        webview.start(gui='edgechromium',private_mode=False,storage_path=str(storage/'webview'),icon=str(resources/'frontend/dist/favicon.ico'))
    finally:
        if server:server.stop()
        instance.close()


def main():
    parser=argparse.ArgumentParser(description='LanCher Code Desktop')
    parser.add_argument('--data-dir',type=Path,default=Path(os.environ.get('LOCALAPPDATA',Path.home()))/'LanCherCodeDesktop')
    parser.add_argument('--resources',type=Path,default=resource_root())
    parser.add_argument('--smoke-test',action='store_true',help=argparse.SUPPRESS)
    args=parser.parse_args()
    if args.smoke_test:
        if '--data-dir' not in sys.argv:parser.error('桌面验收必须显式指定独立 --data-dir。')
        from .acceptance import smoke
        run(args.resources.resolve(),args.data_dir.resolve(),smoke=smoke)
        import json
        report=json.loads((args.data_dir/'acceptance/result.json').read_text(encoding='utf-8'))
        if not report.get('passed'):raise SystemExit(1)
        return
    try:run(args.resources.resolve(),args.data_dir.resolve())
    except Exception as error:
        logging.exception('桌面启动或退出失败')
        ctypes.windll.user32.MessageBoxW(None,'桌面工作台未能启动或完成收尾。\n'+str(error)+'\n请查看桌面数据目录中的日志。','LanCher Code Desktop',0x10)
        raise

if __name__=='__main__':main()
