"""验证真实 SDK 的文件/命令/会话通过 Web 宿主完整运行。"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
import re
import sys
import threading
import time
import zipfile

import httpx
import pytest

from provider_helpers import Reply


def request(client, method, path, **kwargs):
    response = client.request(method, path, **kwargs)
    assert response.status_code < 400, response.text
    return response.json()


def project(client, path):
    return request(client, 'POST', '/api/projects', json={'path': str(path)})['id']


def chat(client, project_id, title='测试对话'):
    return request(client, 'POST', '/api/chats', json={'project_id': project_id, 'title': title})['id']


def detail(client, identity):
    return request(client, 'GET', f'/api/chats/{identity}')


def submit(client, identity, prompt):
    return request(client, 'POST', f'/api/chats/{identity}/turns', json={'prompt': prompt})


def action(client, identity, value, **kwargs):
    return request(client, 'POST', f'/api/chats/{identity}/actions', json={'action': value, **kwargs})


def wait(client, identity, predicate, timeout=25):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = detail(client, identity)
        if predicate(state):
            return state
        time.sleep(0.025)
    raise AssertionError(f"会话等待超时: {identity}: {state.get('status')}")


def complete(client, identity, outcome='allow_once', timeout=50):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = detail(client, identity)
        for permission in state.get('permissions', []):
            request(client, 'POST', f"/api/chats/{identity}/permissions/{permission['request_id']}",
                    json={'outcome': outcome})
        if state['status'] in {'completed', 'failed', 'cancelled', 'interrupted'}:
            return state
        time.sleep(0.025)
    raise AssertionError(f'任务未结束: {identity}')


def traces(state, name=None):
    return [entry for message in state['messages'] for entry in message.get('trace', {}).get('entries', [])
            if entry['kind'] == 'tool_result' and (name is None or entry['tool_name'] == name)]


def command(text, **kwargs):
    return ('run_command', {'description': '在专用临时工程执行测试', 'command': text, 'yield_ms': 60000, **kwargs})


def test_bootstrap_is_shared_config_but_secrets_not_forwarded(client, isolated):
    import lancher_code
    root, home, workspace = isolated
    source = Path(lancher_code.__file__).resolve()
    assert source.is_relative_to(Path(__file__).resolve().parents[1] / '.venv')
    bootstrap = request(client, 'GET', '/api/bootstrap')
    assert {'projects', 'chats', 'models', 'commands', 'watermark', 'preferences'} <= bootstrap.keys()
    assert 'fixture-secret-never-exposed' not in json.dumps(bootstrap)
    created = project(client, workspace)
    assert project(client, workspace) == created
    assert request(client, 'GET', '/api/settings', params={'project_id': created})['configured']
    assert client.get('/api/bootstrap', headers={'Origin': 'https://attacker.example'}).status_code == 403
    assert client.get('/api/bootstrap', headers={'Host': 'attacker.example'}).status_code == 403


def test_native_file_tools_and_search_use_selected_project(client, isolated, provider):
    _, _, workspace = isolated
    (workspace / 'module.txt').write_text('alpha\nbeta\n', encoding='utf-8')
    provider.plans['原生文件工具'] = [
        Reply(tools=[('read_file', {'path': 'module.txt'})]),
        Reply(tools=[('edit_file', {'path': 'module.txt', 'old_text': 'beta', 'new_text': 'gamma'})]),
        Reply(tools=[('write_file', {'path': 'created.txt', 'content': 'created by native SDK\n'})]),
        Reply(tools=[('glob', {'pattern': '*.txt'}), ('grep', {'pattern': 'gamma', 'path': 'module.txt'})]),
        Reply(text='文件与搜索完成'),
    ]
    identity = chat(client, project(client, workspace))
    submit(client, identity, '原生文件工具')
    state = complete(client, identity)
    assert state['status'] == 'completed'
    assert (workspace / 'module.txt').read_text(encoding='utf-8') == 'alpha\ngamma\n'
    assert (workspace / 'created.txt').read_text(encoding='utf-8') == 'created by native SDK\n'
    assert {entry['tool_name'] for entry in traces(state)} == {'read_file', 'edit_file', 'write_file', 'glob', 'grep'}
    assert all(entry['ok'] is True for entry in traces(state))
    assert state['sdk_session_id'] and (workspace / '.lancher' / 'sessions' / state['sdk_session_id']).is_dir()
    modified = request(client, 'GET', f'/api/chats/{identity}/file', params={'path': 'module.txt'})
    assert '-beta' in modified['diff'] and '+gamma' in modified['diff']
    added = request(client, 'GET', f'/api/chats/{identity}/file', params={'path': 'created.txt'})
    assert '+created by native SDK' in added['diff']
    listing = request(client, 'GET', f"/api/projects/{state['project_id']}/files", params={'chat_id': identity})
    statuses = {row['path']: row['status'] for row in listing['files']}
    assert statuses['module.txt'] == 'modified' and statuses['created.txt'] == 'added'


def test_project_fifo_and_different_project_parallel(client, isolated, provider):
    _, _, workspace = isolated
    other = workspace.parent / 'other-project'
    other.mkdir()
    gate = threading.Event()
    provider.plans['先运行'] = [Reply(text='第一任务完成', gate=gate)]
    first_project = project(client, workspace)
    first, second = chat(client, first_project), chat(client, first_project)
    third = chat(client, project(client, other))
    submit(client, first, '先运行')
    wait(client, first, lambda value: any(row['prompt'] == '先运行' for row in provider.requests))
    submit(client, second, '同项目后运行')
    assert detail(client, second)['status'] == 'queued'
    submit(client, third, '另一个项目并行')
    parallel = complete(client, third)
    assert parallel['status'] == 'completed' and detail(client, first)['status'] == 'running'
    assert not any(row['prompt'] == '同项目后运行' for row in provider.requests)
    gate.set()
    assert complete(client, first)['status'] == 'completed'
    assert complete(client, second)['status'] == 'completed'
    prompts = [row['prompt'] for row in provider.requests]
    assert prompts.index('先运行') < prompts.index('同项目后运行')


def test_cancel_queued_chat_never_starts_provider(client, isolated, provider):
    gate = threading.Event()
    provider.plans['占用项目前台'] = [Reply(text='等待取消', gate=gate)]
    project_id = project(client, isolated[2])
    first, queued = chat(client, project_id), chat(client, project_id)
    submit(client, first, '占用项目前台')
    wait(client, first, lambda _value: bool(provider.requests))
    submit(client, queued, '取消排队')
    assert detail(client, queued)['status'] == 'queued'
    request(client, 'POST', f'/api/chats/{queued}/stop', json={'scope': 'turn'})
    assert detail(client, queued)['status'] == 'cancelled'
    request(client, 'POST', f'/api/chats/{first}/stop', json={'scope': 'turn'})
    assert detail(client, first)['status'] == 'cancelled'
    assert not any(row['prompt'] == '取消排队' for row in provider.requests)


def test_stop_keeps_followup_and_explicit_resume(client, isolated, provider):
    gate = threading.Event()
    provider.plans['慢任务'] = [Reply(text='慢任务完成', gate=gate)]
    identity = chat(client, project(client, isolated[2]))
    submit(client, identity, '慢任务')
    wait(client, identity, lambda _value: bool(provider.requests))
    action(client, identity, 'queue_add', text='恢复后的输入', delivery='follow_up')
    request(client, 'POST', f'/api/chats/{identity}/stop', json={'scope': 'turn'})
    state = detail(client, identity)
    assert state['status'] == 'cancelled' and state['queue_paused']
    assert len(state['queue']) == 1
    action(client, identity, 'queue_resume')
    state = complete(client, identity)
    assert state['status'] == 'completed' and state['queue'] == []
    assert [message['content'] for message in state['messages'] if message['role'] == 'user'] == ['慢任务', '恢复后的输入']


def test_external_path_approval_denial_and_stale_request(client, isolated, provider):
    workspace = isolated[2]
    outside = workspace.parent / 'outside.txt'
    provider.plans['拒绝项目外写入'] = [Reply(tools=[('write_file', {'path': str(outside), 'content': 'not allowed'})]), Reply(text='拒绝已处理')]
    identity = chat(client, project(client, workspace))
    submit(client, identity, '拒绝项目外写入')
    waiting = wait(client, identity, lambda value: bool(value['permissions']))
    permission_id = waiting['permissions'][0]['request_id']
    state = complete(client, identity, outcome='deny')
    assert state['status'] == 'completed' and not outside.exists()
    result = traces(state, 'write_file')[0]
    assert not result['ok'] and result['metadata']['error_code'] == 'permission_user_denied'
    assert client.post(f'/api/chats/{identity}/permissions/{permission_id}', json={'outcome': 'allow_once'}).status_code == 409


def test_web_and_tui_share_session_history_and_writer_lock(client, isolated, provider):
    from lancher_code.agent.skills import SkillsService
    from lancher_code.config.loader import load_config
    from lancher_code.errors import ConfigError
    from lancher_code.permissions.storage import PermissionStorage
    from lancher_code.sdk import create_agent
    from lancher_code.sessions.storage import SessionBusyError
    _, home, workspace = isolated
    identity = chat(client, project(client, workspace))
    submit(client, identity, '来自 WebUI')
    state = complete(client, identity)
    session_id = state['sdk_session_id']

    async def tui_turn(expect_busy):
        agent = create_agent(load_config(home / '.lancher' / 'lancher.yaml').to_agent_config(), cwd=workspace,
            provider_factory=lambda _config: provider, enable_mcp=False, permission_storage=PermissionStorage(project_rules_path=workspace / '.lancher' / 'permissions.yaml', user_rules_path=home / '.lancher' / 'permissions.yaml'),
            skills_service=SkillsService(workspace, user_root=home))
        try:
            await agent.ready()
            if expect_busy:
                with pytest.raises((SessionBusyError, ConfigError)):
                    agent.resume_session(session_id)
            else:
                agent.resume_session(session_id)
                result = await agent.run('来自 TUI')
                assert result.status == 'completed'
        finally:
            await agent.close()

    client.portal.call(tui_turn, True)
    action(client, identity, 'release')
    client.portal.call(tui_turn, False)
    refreshed = detail(client, identity)
    assert [message['content'] for message in refreshed['messages'] if message['role'] == 'user'] == ['来自 WebUI', '来自 TUI']
    submit(client, identity, 'WebUI 再次继续')
    final = complete(client, identity)
    assert [message['content'] for message in final['messages'] if message['role'] == 'user'] == ['来自 WebUI', '来自 TUI', 'WebUI 再次继续']


def test_known_and_unknown_request_usage_are_not_fabricated(client, isolated, provider):
    from lancher_code.usage.models import MessageUsage
    provider.plans['未知用量'] = [Reply(text='未上报', usage=MessageUsage())]
    project_id = project(client, isolated[2])
    known = chat(client, project_id)
    submit(client, known, '已知用量')
    first = complete(client, known)
    assert first['usage']['answer']['input_tokens'] == 7
    assert first['usage']['answer']['cached_input_tokens'] == 2
    unknown = chat(client, project_id)
    submit(client, unknown, '未知用量')
    second = complete(client, unknown)
    assert second['usage']['answer']['usage']['input_tokens'] is None
    assert second['usage']['answer']['usage']['output_tokens'] is None
    assert second['usage']['project']['request_count'] >= 2
    assert second['usage']['server']['request_count'] >= 2


def test_native_local_wheel_install_without_external_network(client, isolated, provider):
    workspace = isolated[2]
    wheel = workspace / 'tiny_fixture-0.0.1-py3-none-any.whl'
    with zipfile.ZipFile(wheel, 'w') as archive:
        archive.writestr('tiny_fixture/__init__.py', 'VALUE = 42\n')
        archive.writestr('tiny_fixture-0.0.1.dist-info/METADATA', 'Metadata-Version: 2.1\nName: tiny-fixture\nVersion: 0.0.1\n')
        archive.writestr('tiny_fixture-0.0.1.dist-info/WHEEL', 'Wheel-Version: 1.0\nGenerator: fixture\nRoot-Is-Purelib: true\nTag: py3-none-any\n')
        archive.writestr('tiny_fixture-0.0.1.dist-info/RECORD', '')
    executable = sys.executable.replace("'", "''")
    provider.plans['本地离线安装'] = [
        Reply(tools=[command(f"& '{executable}' -m venv localenv")]),
        Reply(tools=[command("& './localenv/Scripts/python.exe' -m pip --disable-pip-version-check install --no-cache-dir --no-index --no-deps './tiny_fixture-0.0.1-py3-none-any.whl'")]),
        Reply(tools=[command("& './localenv/Scripts/python.exe' -c 'import tiny_fixture; print(tiny_fixture.VALUE)'")]),
        Reply(text='离线安装完成'),
    ]
    identity = chat(client, project(client, workspace))
    submit(client, identity, '本地离线安装')
    final = complete(client, identity, timeout=90)
    results = traces(final, 'run_command')
    assert final['status'] == 'completed' and len(results) == 3
    assert all(entry['ok'] for entry in results)
    assert 'Successfully installed tiny-fixture-0.0.1' in results[1]['metadata']['content']
    assert '42' in results[2]['metadata']['content']
    assert (workspace / 'localenv' / 'Lib' / 'site-packages' / 'tiny_fixture').is_dir()


def test_native_background_http_process_input_log_and_stop(client, isolated, provider):
    workspace = isolated[2]
    code = '''from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import sys
import threading
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'health-ok')
    def log_message(self, *args):
        pass
server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
print('PORT=' + str(server.server_port), flush=True)
for line in sys.stdin:
    print('INPUT=' + line.strip(), flush=True)
server.shutdown()
'''
    executable = sys.executable.replace("'", "''")
    gate = threading.Event()
    provider.plans['启动后台 HTTP'] = [Reply(tools=[('write_file', {'path': 'server.py', 'content': code})]),
        Reply(tools=[command(f"& '{executable}' -u server.py", yield_ms=200, lifetime='turn')]), Reply(text='后台已启动', gate=gate)]
    identity = chat(client, project(client, workspace))
    submit(client, identity, '启动后台 HTTP')
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        running = detail(client, identity)
        for permission in running['permissions']:
            request(client, 'POST', f"/api/chats/{identity}/permissions/{permission['request_id']}", json={'outcome': 'allow_once'})
        if traces(running, 'run_command'):
            break
        time.sleep(0.025)
    else:
        raise AssertionError('后台测试进程没有开始')
    process_id = traces(running, 'run_command')[0]['metadata']['process_id']
    action(client, identity, 'process_background', process_id=process_id)
    gate.set()
    final = complete(client, identity)
    assert final['status'] == 'completed'
    read = action(client, identity, 'process_read', process_id=process_id)
    port = re.search(r'PORT=(\d+)', json.dumps(read))
    assert port, read
    assert httpx.get(f'http://127.0.0.1:{port.group(1)}', timeout=3).text == 'health-ok'
    action(client, identity, 'process_write', process_id=process_id, text='native-input\n')
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        output = action(client, identity, 'process_read', process_id=process_id)
        if 'INPUT=native-input' in json.dumps(output):
            break
        time.sleep(0.05)
    else:
        raise AssertionError('没有读取到进程输入回显')
    action(client, identity, 'process_stop', process_id=process_id)
    stopped = detail(client, identity)
    assert all(row['status'] not in {'running', 'starting'} for row in stopped['processes'])
    with pytest.raises((httpx.ConnectError, httpx.ConnectTimeout)):
        httpx.get(f'http://127.0.0.1:{port.group(1)}', timeout=1)




def test_complete_command_catalog_and_control_dispatch(client, isolated, provider):
    from lancher_code.tui.commands import create_default_slash_command_registry
    expected = {item.name for item in create_default_slash_command_registry().list_all()}
    bootstrap = request(client, 'GET', '/api/bootstrap')
    assert {item['name'] for item in bootstrap['commands']} == expected
    identity = chat(client, project(client, isolated[2]))
    completions = request(client, 'GET', '/api/commands/complete', params={'chat_id': identity, 'text': '/'})
    assert completions['candidates']
    samples = ['/status', '/model', '/access', '/session list', '/tasks list', '/skills list', '/mcp list', '/settings', '/exit']
    for text in samples:
        result = request(client, 'POST', f'/api/chats/{identity}/commands', json={'text': text})
        assert result['handled']
    request(client, 'POST', f'/api/chats/{identity}/commands', json={'text': '/discuss'})
    assert detail(client, identity)['phase'] == 'discuss'
    request(client, 'POST', f'/api/chats/{identity}/commands', json={'text': '/do'})
    request(client, 'POST', f'/api/chats/{identity}/commands', json={'text': '/access project'})
    assert detail(client, identity)['access'] == 'project'
    request(client, 'POST', f'/api/chats/{identity}/commands', json={'text': '/model test/two'})
    assert detail(client, identity)['model_ref'] == 'test/two'
    assert provider.requests == []
    assert client.post(f'/api/chats/{identity}/commands', json={'text': '/not-real-command'}).status_code == 400


def test_busy_settings_wait_for_safe_application_and_broadcast(client, isolated, provider):
    gate = threading.Event()
    provider.plans['忙时设置'] = [Reply(text='完成忙时请求', gate=gate)]
    project_id = project(client, isolated[2])
    identity = chat(client, project_id)
    submit(client, identity, '忙时设置')
    wait(client, identity, lambda _value: bool(provider.requests))
    assert client.post(f'/api/chats/{identity}/actions', json={'action': 'model', 'model_ref': 'test/two'}).status_code == 409
    settings = request(client, 'GET', '/api/settings', params={'project_id': project_id})
    data = {key: settings['config'][key] for key in ('providers', 'default_model')}
    data['default_model'] = 'test/two'
    payload = {'domain': 'models', 'project_id': project_id, 'revision': settings['revision'], 'data': data}
    saved = request(client, 'PATCH', '/api/settings', json=payload)
    assert identity in saved['pending'] and detail(client, identity)['pending_config']
    assert client.patch('/api/settings', json=payload).status_code == 409
    gate.set()
    wait(client, identity, lambda value: value['status'] == 'completed' and not value['pending_config'])
    new = chat(client, project_id)
    assert detail(client, new)['model_ref'] == 'test/two'
    rows = client.portal.call(lambda: client.app.state.manager.store.events_after(0))
    assert any(row['kind'] == 'config_updated' and identity in row['pending'] for row in rows)
    assert 'fixture-secret-never-exposed' not in json.dumps(rows)


def test_global_event_replay_ids_and_expired_cursor_reset(client, isolated):
    identity = chat(client, project(client, isolated[2]))
    async def verify():
        manager = client.app.state.manager
        target = manager.get_chat(identity)
        cursor = manager.store.watermark
        first = manager.emit({'kind': 'lab_log', 'text': 'first'}, chat=target)
        second = manager.emit({'kind': 'lab_log', 'text': 'second'}, chat=target)
        stream = manager.events_after(cursor)
        received = [await asyncio.wait_for(anext(stream), 1), await asyncio.wait_for(anext(stream), 1)]
        await stream.aclose()
        assert [row['sequence'] for row in received] == [cursor + 1, cursor + 2]
        assert [row['text'] for row in received] == ['first', 'second']
        assert all(row['chat_id'] == identity and row['project_id'] == target['project_id'] for row in received)
        manager.store.db.execute('DELETE FROM events WHERE sequence<=?', (cursor,))
        manager.store.db.commit()
        reset = manager.events_after(1)
        value = await asyncio.wait_for(anext(reset), 1)
        await reset.aclose()
        assert value['kind'] == 'reset_required' and value['sequence'] == second['sequence']
    client.portal.call(verify)




def test_shutdown_restart_recovers_complete_sdk_history(isolated, provider):
    from fastapi.testclient import TestClient
    from webui.api import create_app
    root, home, workspace = isolated
    arguments = {'root': root, 'user_home': home, 'provider_factory': lambda _config: provider, 'enable_mcp': False}
    with TestClient(create_app(**arguments), raise_server_exceptions=False) as first:
        identity = chat(first, project(first, workspace))
        submit(first, identity, '保存完整历史')
        before = complete(first, identity)
        assert before['status'] == 'completed'
        session_id = before['sdk_session_id']
    with TestClient(create_app(**arguments), raise_server_exceptions=False) as second:
        restored = detail(second, identity)
        assert restored['messages'] == before['messages'] and restored['sdk_session_id'] == session_id
        submit(second, identity, '服务重启后继续')
        after = complete(second, identity)
        assert after['status'] == 'completed' and after['sdk_session_id'] == session_id
        assert [row['content'] for row in after['messages'] if row['role'] == 'user'] == ['保存完整历史', '服务重启后继续']


def test_independent_http_server_start_and_graceful_shutdown(isolated):
    import os
    import queue
    import subprocess
    root, home, _workspace = isolated
    startup = root / 'smoke_server.py'
    startup.write_text('''import json
import uvicorn
from pathlib import Path
from webui.api import create_app
app = create_app(root=Path(''' + repr(str(root)) + '''), user_home=Path(''' + repr(str(home)) + '''), enable_mcp=False)
class SmokeServer(uvicorn.Server):
    async def startup(self, sockets=None):
        await super().startup(sockets)
        port = self.servers[0].sockets[0].getsockname()[1]
        print(json.dumps({'port': port}), flush=True)
server = SmokeServer(uvicorn.Config(app, host='127.0.0.1', port=0, log_level='error'))
app.state.shutdown_callback = lambda: setattr(server, 'should_exit', True)
server.run()
''', encoding='utf-8')
    env = os.environ.copy()
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    env['PYTHONPATH'] = str(Path(__file__).resolve().parents[1])
    process = subprocess.Popen([sys.executable, str(startup)], cwd=root, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8',
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    lines = queue.Queue()
    reader = threading.Thread(target=lambda: lines.put(process.stdout.readline()), daemon=True)
    reader.start()
    try:
        first = lines.get(timeout=20)
        assert first, process.stderr.read() if process.poll() is not None else '没有收到启动确认'
        port = json.loads(first)['port']
        with httpx.Client(base_url=f'http://127.0.0.1:{port}', timeout=10, trust_env=False) as client:
            bootstrap = client.get('/api/bootstrap')
            assert bootstrap.status_code == 200 and bootstrap.json()['name'] == 'LanCher Code WebUI'
            assert client.get('/').status_code == 200
            shutdown = client.post('/api/shutdown')
            assert shutdown.status_code == 200 and shutdown.json()['closed']
        assert process.wait(timeout=20) == 0
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=10)
        process.stdout.close()
        process.stderr.close()


def test_fifth_project_slot_can_be_cancelled_before_provider_start(client, isolated, provider):
    gates = [threading.Event() for _ in range(4)]
    identities = []
    for index in range(5):
        workspace = isolated[2].parent / f'slot-project-{index}'
        workspace.mkdir()
        identity = chat(client, project(client, workspace))
        identities.append(identity)
        prompt = f'项目slot-{index}'
        if index < 4:
            provider.plans[prompt] = [Reply(text='任务完成', gate=gates[index])]
        submit(client, identity, prompt)
        if index < 4:
            wait(client, identity, lambda _state, current=prompt: any(row['prompt'] == current for row in provider.requests))
    assert detail(client, identities[4])['status'] == 'queued'
    request(client, 'POST', f'/api/chats/{identities[4]}/stop', json={'scope': 'turn'})
    assert detail(client, identities[4])['status'] == 'cancelled'
    for gate in gates:
        gate.set()
    for identity in identities[:4]:
        assert complete(client, identity)['status'] == 'completed'
    assert not any(row['prompt'] == '项目slot-4' for row in provider.requests)


def test_late_followup_after_empty_queue_config_save_uses_resumed_queue(client, isolated, provider):
    gate = threading.Event()
    provider.plans['空队列保存配置'] = [Reply(text='第一轮完成', gate=gate)]
    project_id = project(client, isolated[2])
    identity = chat(client, project_id)
    submit(client, identity, '空队列保存配置')
    wait(client, identity, lambda _value: bool(provider.requests))
    assert detail(client, identity)['queue'] == []
    settings = request(client, 'GET', '/api/settings', params={'project_id': project_id})
    models = {key: settings['config'][key] for key in ('providers', 'default_model')}
    models['providers']['test']['name'] = '目录更新'
    saved = request(client, 'PATCH', '/api/settings', json={'domain': 'models', 'project_id': project_id,
                     'revision': settings['revision'], 'data': models})
    assert identity in saved['pending']
    action(client, identity, 'queue_add', text='配置保存后才追加', delivery='follow_up')
    gate.set()
    final = wait(client, identity, lambda state: state['status'] == 'completed' and state['queue'] == []
        and len([row for row in state['messages'] if row['role'] == 'user']) == 2)
    assert not final['pending_config'] and not final['queue_paused']
    assert [row['content'] for row in final['messages'] if row['role'] == 'user'] == ['空队列保存配置', '配置保存后才追加']


def test_removed_saved_model_falls_back_without_losing_history(client, isolated, provider):
    project_id = project(client, isolated[2])
    identity = chat(client, project_id)
    submit(client, identity, '旧模型历史')
    original = complete(client, identity)
    session_id = original['sdk_session_id']
    action(client, identity, 'release')
    settings = request(client, 'GET', '/api/settings', params={'project_id': project_id})
    models = {key: settings['config'][key] for key in ('providers', 'default_model')}
    models['providers']['test']['models'].pop('one')
    models['default_model'] = 'test/two'
    request(client, 'PATCH', '/api/settings', json={'domain': 'models', 'project_id': project_id,
                'revision': settings['revision'], 'data': models})
    submit(client, identity, '删除模型后继续')
    recovered = complete(client, identity)
    assert recovered['status'] == 'completed' and recovered['sdk_session_id'] == session_id
    assert recovered['model_ref'] == 'test/two'
    assert provider.requests[-1]['model'] == 'fixture-two'
    assert [row['content'] for row in recovered['messages'] if row['role'] == 'user'] == ['旧模型历史', '删除模型后继续']



def test_file_preview_and_sdk_both_honor_shared_read_deny(client, isolated, provider):
    workspace = isolated[2]
    protected = workspace / 'protected.txt'
    protected.write_text('PRIVATE-FIXTURE-CONTENT', encoding='utf-8')
    project_id = project(client, workspace)
    identity = chat(client, project_id)
    settings = request(client, 'GET', '/api/settings', params={'project_id': project_id})
    rule = {'match': 'ReadFile(protected.txt)', 'result': 'deny', 'match_kind': 'exact'}
    request(client, 'PATCH', '/api/settings', json={'domain': 'rules', 'scope': 'project',
            'project_id': project_id, 'revision': settings['revision'], 'data': [rule]})
    response = client.get(f'/api/chats/{identity}/file', params={'path': 'protected.txt'})
    assert response.status_code == 403 and 'PRIVATE-FIXTURE-CONTENT' not in response.text
    listing = request(client, 'GET', f'/api/projects/{project_id}/files', params={'chat_id': identity})
    assert 'protected.txt' not in {row['path'] for row in listing['files']}
    provider.plans['共享规则拒绝原生读取'] = [Reply(tools=[('read_file', {'path': 'protected.txt'})]), Reply(text='读取拒绝已处理')]
    submit(client, identity, '共享规则拒绝原生读取')
    final = complete(client, identity)
    result = traces(final, 'read_file')[0]
    assert final['status'] == 'completed' and result['ok'] is False
    assert result['metadata']['error_code'] == 'permission_rule_deny'
    assert 'PRIVATE-FIXTURE-CONTENT' not in json.dumps(final)




def test_same_project_followup_rejoins_fifo_after_already_queued_chat(client, isolated, provider):
    gate = threading.Event()
    provider.plans['FIFO-A初始'] = [Reply(text='A初始完成', gate=gate)]
    project_id = project(client, isolated[2])
    first, second = chat(client, project_id, 'A'), chat(client, project_id, 'B')
    submit(client, first, 'FIFO-A初始')
    wait(client, first, lambda _state: any(row['prompt'] == 'FIFO-A初始' for row in provider.requests))
    submit(client, second, 'FIFO-B先排队')
    assert detail(client, second)['status'] == 'queued'
    action(client, first, 'queue_add', text='FIFO-A后追加', delivery='follow_up')
    gate.set()
    complete(client, second)
    final = wait(client, first, lambda state: state['status'] == 'completed' and not state['queue']
        and len([row for row in state['messages'] if row['role'] == 'user']) == 2)
    assert final['status'] == 'completed'
    assert [row['prompt'] for row in provider.requests] == ['FIFO-A初始', 'FIFO-B先排队', 'FIFO-A后追加']


def test_manual_pause_on_empty_queue_survives_later_followup(client, isolated, provider):
    gate = threading.Event()
    provider.plans['人工暂停初始轮次'] = [Reply(text='初始轮次完成', gate=gate)]
    identity = chat(client, project(client, isolated[2]))
    submit(client, identity, '人工暂停初始轮次')
    wait(client, identity, lambda _state: bool(provider.requests))
    assert detail(client, identity)['queue'] == []
    action(client, identity, 'queue_pause')
    action(client, identity, 'queue_add', text='人工暂停后追加', delivery='follow_up')
    gate.set()
    paused = wait(client, identity, lambda state: state['status'] == 'completed')
    assert paused['queue_paused'] and len(paused['queue']) == 1
    assert [row['prompt'] for row in provider.requests] == ['人工暂停初始轮次']
    action(client, identity, 'queue_resume')
    resumed = wait(client, identity, lambda state: state['status'] == 'completed' and not state['queue']
        and len([row for row in state['messages'] if row['role'] == 'user']) == 2)
    assert not resumed['queue_paused']
    assert [row['prompt'] for row in provider.requests] == ['人工暂停初始轮次', '人工暂停后追加']
