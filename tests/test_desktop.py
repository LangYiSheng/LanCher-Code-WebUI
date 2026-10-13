"""桌面测试仅使用专用资源、配置和数据目录。"""
import http.client
from pathlib import Path
from fastapi.testclient import TestClient
from desktop.server import DesktopServer,COOKIE
from webui.api import create_app


def test_resource_and_runtime_roots_are_separate(isolated,tmp_path):
    resources,home,_=isolated
    (resources/'frontend/dist/index.html').write_text('<html><head><title>fixture</title></head><body></body></html>',encoding='utf-8')
    runtime=tmp_path/'desktop-data'
    with TestClient(create_app(resources,user_home=home,runtime_root=runtime,desktop=True,enable_mcp=False)) as client:
        assert client.get('/api/bootstrap').status_code==200
        assert '/desktop-host.js' in client.get('/').text
        assert client.get('/desktop-host.js').text.startswith('window.__LANCHER_DESKTOP__=true;')
        assert "script-src 'self'" in client.get('/').headers['content-security-policy']
        assert client.app.state.manager.root==runtime.resolve()
        assert client.app.state.manager.sdk_snapshot['commit']=='00e0797-fixture'
    assert (runtime/'data/webui.sqlite3').exists()
    assert not (resources/'data/webui.sqlite3').exists()


def test_browser_mode_has_no_desktop_marker(client):
    assert '__LANCHER_DESKTOP__' not in client.get('/').text


def test_desktop_cookie_and_origin_guards(isolated,tmp_path):
    resources,_,_=isolated
    server=DesktopServer(resources,tmp_path/'desktop',enable_mcp=False)
    try:
        with TestClient(server.app) as client:
            assert client.get('/api/bootstrap').status_code==401
            assert client.get('/desktop/start?token=wrong').status_code==401
            response=client.get('/desktop/start',params={'token':server.token},follow_redirects=False)
            assert response.status_code==303
            assert 'HttpOnly' in response.headers['set-cookie']
            assert 'SameSite=strict' in response.headers['set-cookie']
            assert client.get('/api/bootstrap').status_code==200
            assert client.post('/api/projects',json={'path':str(tmp_path)},headers={'Origin':'http://evil.invalid'}).status_code==403
            assert client.post('/desktop/activate').status_code==401
            assert client.post('/desktop/activate',headers={'x-desktop-token':server.token}).status_code==200
    finally:server.socket.close()


def test_live_server_uses_owned_ephemeral_port_and_closes(isolated,tmp_path):
    resources,_,_=isolated
    server=DesktopServer(resources,tmp_path/'live',enable_mcp=False)
    server.start()
    connection=http.client.HTTPConnection('127.0.0.1',server.port,timeout=5)
    try:
        assert server.port!=8765
        connection.request('GET','/api/status',headers={'Cookie':f'{COOKIE}={server.token}'})
        response=connection.getresponse();assert response.status==200;response.read()
        assert server.activity()=={'tasks':0,'processes':0}
    finally:connection.close();server.stop()
    assert not server.thread.is_alive()


def test_ui_state_survives_ephemeral_port_change(isolated,tmp_path):
    resources,_,_=isolated
    storage=tmp_path/'persistent'
    first=DesktopServer(resources,storage,enable_mcp=False)
    try:
        with TestClient(first.app) as client:
            client.cookies.set(COOKIE,first.token)
            assert client.post('/desktop/ui-state',json={'key':'draft:chat-a','value':'中文未发送草稿'}).status_code==200
            assert client.post('/desktop/ui-state',json={'key':None,'value':'bad'}).status_code==400
    finally:first.socket.close()
    second=DesktopServer(resources,storage,enable_mcp=False)
    try:
        assert second.port!=first.port
        with TestClient(second.app) as client:
            client.cookies.set(COOKIE,second.token)
            assert '中文未发送草稿' in client.get('/desktop-host.js').text
            assert second.ui_state['draft:chat-a']=='中文未发送草稿'
    finally:second.socket.close()


def test_native_bridge_rejects_foreign_page_before_window_operation():
    from types import SimpleNamespace
    from desktop.bridge import DesktopBridge
    import pytest
    server=SimpleNamespace(port=12345)
    bridge=DesktopBridge(server)
    bridge._window=SimpleNamespace(get_current_url=lambda:'https://example.com/')
    with pytest.raises(PermissionError):bridge.minimize()
    with pytest.raises(PermissionError):bridge.import_config()


def test_invalid_configuration_import_keeps_source_and_desktop_copy(isolated,tmp_path,monkeypatch):
    from types import SimpleNamespace
    import pytest
    from desktop.bridge import DesktopBridge
    from lancher_code.errors import ConfigError
    resources,source_home,_=isolated
    source=source_home/'.lancher/lancher.yaml';source.write_text('providers: {}\ndefault_model: missing/model\n',encoding='utf-8')
    source_bytes=source.read_bytes()
    server=DesktopServer(resources,tmp_path/'import',enable_mcp=False)
    target=server.home/'.lancher/lancher.yaml';target.write_text('keep-existing-copy',encoding='utf-8')
    server.start()
    bridge=DesktopBridge(server);bridge._window=SimpleNamespace(get_current_url=lambda:server.url)
    monkeypatch.setattr(Path,'home',classmethod(lambda cls:source_home))
    try:
        with pytest.raises(ConfigError):bridge.import_config()
        assert source.read_bytes()==source_bytes
        assert target.read_text()=='keep-existing-copy'
    finally:server.stop()


def test_directory_picker_uses_host_adapter_without_python_subprocess(client,tmp_path):
    chosen=tmp_path/'chosen-project';chosen.mkdir()
    client.app.state.directory_picker=lambda:{'path':str(chosen),'cancelled':False}
    result=client.post('/api/projects/pick')
    assert result.status_code==200
    assert result.json()=={'path':str(chosen),'cancelled':False}


def test_native_directory_picker_validates_result_and_cancel(tmp_path,monkeypatch):
    from types import SimpleNamespace
    import pytest
    from desktop.bridge import DesktopBridge
    import sys
    monkeypatch.setitem(sys.modules,'System',SimpleNamespace(Action=lambda callback:callback))
    bridge=DesktopBridge(SimpleNamespace(port=12345,storage=tmp_path))
    window=SimpleNamespace(get_current_url=lambda:'http://127.0.0.1:12345/',create_file_dialog=lambda *args,**kwargs:(str(tmp_path),))
    window.native=SimpleNamespace(Invoke=lambda action:action())
    bridge._window=window
    assert bridge._pick_directory()=={'path':str(tmp_path.resolve()),'cancelled':False}
    window.create_file_dialog=lambda *args,**kwargs:None
    assert bridge._pick_directory()=={'path':None,'cancelled':True}
    window.create_file_dialog=lambda *args,**kwargs:(str(tmp_path/'missing'),)
    with pytest.raises(ValueError):bridge._pick_directory()
