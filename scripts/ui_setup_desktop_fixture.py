"""桌面激活浏览器验收：真实导入桥接，窗口按钮使用测试适配器。"""
from pathlib import Path
from types import SimpleNamespace
import json
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'data' / 'ui-setup-acceptance' / 'activation2' / 'desktop'


def main():
    if any(path.is_symlink() for path in (ROOT / 'data', FIXTURE.parent, FIXTURE)):
        raise RuntimeError('验收目录不能是链接。')
    (FIXTURE / 'vendor').mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / 'vendor' / 'snapshot.json', FIXTURE / 'vendor' / 'snapshot.json')
    shutil.copytree(ROOT / 'frontend' / 'dist', FIXTURE / 'frontend' / 'dist', dirs_exist_ok=True)
    source_home = FIXTURE / 'source-home'
    (source_home / '.lancher').mkdir(parents=True, exist_ok=True)
    (FIXTURE / 'project').mkdir(exist_ok=True)
    sys.path.insert(0, str(ROOT))
    from desktop.server import DesktopServer
    from desktop.bridge import DesktopBridge
    from fastapi.responses import Response
    from starlette.concurrency import run_in_threadpool
    server = DesktopServer(FIXTURE, FIXTURE / 'desktop-runtime', enable_mcp=False)
    source = source_home / '.lancher' / 'lancher.yaml'
    if not source.exists():
        source.write_text(f'''providers:
  source:
    name: 我的供应商
    protocol: openai
    base_url: http://127.0.0.1:{server.port}/fixture-model-api/v1
    api_key: fixture-desktop-key
    models:
      one:
        model_name: fixture-one
      mini:
        model_name: discovered-mini
        display_name: 我的 Mini
default_model: source/mini
''', encoding='utf-8')
    # 仅这个专用验收进程使用虚拟源 home，绝不读取真实用户配置。
    Path.home = classmethod(lambda cls: source_home)
    bridge = DesktopBridge(server)
    bridge._window = SimpleNamespace(get_current_url=lambda: server.url)
    server.app.router.routes = [route for route in server.app.router.routes if getattr(route, 'path', None) != '/desktop-host.js']

    @server.app.get('/desktop-host.js')
    async def host():
        script = 'window.__LANCHER_DESKTOP__=true;window.__LANCHER_UI_STATE__=' + json.dumps(server.ui_state) + ';'
        script += '''window.pywebview={api:{window_state:async()=>({maximized:false}),
        import_config:async()=>{const r=await fetch('/fixture-desktop/import',{method:'POST'});const d=await r.json();if(!r.ok)throw new Error(d.detail);return d;},
        minimize:async()=>{},toggle_maximize:async()=>({maximized:false}),drag:async()=>{},resize:async()=>{},hide:async()=>{},close_status:async()=>({tasks:0,processes:0}),quit:async()=>{}}};'''
        return Response(script, media_type='application/javascript', headers={'Cache-Control': 'no-store'})

    @server.app.post('/fixture-desktop/import')
    async def import_config():
        return await run_in_threadpool(bridge.import_config)

    server.start()
    evidence = {'url': server.url, 'start_url': server.url + '/desktop/start?token=' + server.token, 'cookie': server.token, 'root': str(FIXTURE)}
    (FIXTURE / 'instance.json').write_text(json.dumps(evidence), encoding='utf-8')
    print(evidence['start_url'], flush=True)
    server.thread.join()


if __name__ == '__main__':
    main()
