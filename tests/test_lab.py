"""验证 HTTP 传输层确实驱动隔离的 LanCher SDK，Docker 边界单独说明。"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import time

import pytest
from fastapi.testclient import TestClient

from lab.api import create_app
from lab.manager import LabManager
from lab.tools import RunTests, list_workspace_files, resolve_lab_path


@pytest.fixture
def lab_root(tmp_path):
    (tmp_path / 'vendor').mkdir()
    (tmp_path / 'vendor' / 'snapshot.json').write_text(
        json.dumps({'commit': 'test-snapshot', 'source': 'fixture'}), encoding='utf-8')
    (tmp_path / 'web').mkdir()
    (tmp_path / 'web' / 'index.html').write_text('<!doctype html><title>Lab fixture</title>', encoding='utf-8')
    return tmp_path


@pytest.fixture
def client(lab_root, monkeypatch):
    # 常规测试不读取在线配置、不运行 Docker，也不执行生成代码。
    monkeypatch.setattr(LabManager, '_probe_docker', lambda _self: False)
    with TestClient(create_app(lab_root)) as current:
        yield current


def new_session(client, title='测试会话'):
    response = client.post('/api/sessions', json={'title': title})
    assert response.status_code == 201, response.text
    return response.json()['id']


def detail(client, identity):
    response = client.get(f'/api/sessions/{identity}')
    assert response.status_code == 200, response.text
    return response.json()


def wait_for(client, identity, predicate, timeout=20):
    deadline = time.monotonic() + timeout
    state = None
    while time.monotonic() < deadline:
        state = detail(client, identity)
        if predicate(state):
            return state
        time.sleep(0.025)
    raise AssertionError(f'等待会话状态超时: {state}')


def resolve_all_until_done(client, identity, outcome='deny', timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = detail(client, identity)
        for request in state['pending_permissions']:
            response = client.post(
                f"/api/sessions/{identity}/permissions/{request['request_id']}", json={'outcome': outcome})
            assert response.status_code == 200, response.text
        if state['status'] in {'completed', 'cancelled', 'failed'}:
            return state
        time.sleep(0.025)
    raise AssertionError(f'会话未结束: {state}')


def tool_results(state, name=None):
    results = [event['tool_result'] for event in state['events'] if event['kind'] == 'tool_result_received']
    return [result for result in results if name is None or result['tool_name'] == name]


def test_api_local_origin_and_strict_inputs(client):
    import lancher_code
    # SDK 必须从实验项目独立虚拟环境导入，不能 editable 链接原仓库。
    project_root = Path(__file__).resolve().parents[1]
    sdk_source = Path(lancher_code.__file__).resolve()
    assert sdk_source.is_relative_to(project_root / '.venv')
    status = client.get('/api/status')
    assert status.status_code == 200
    assert status.json()['sdk_commit'] == 'test-snapshot'
    assert not status.json()['live_available']
    assert not status.json()['docker_available']
    assert status.headers['x-content-type-options'] == 'nosniff'
    assert 'frame-ancestors' in status.headers['content-security-policy']
    assert client.get('/api/status', headers={'Host': 'attacker.example'}).status_code == 403
    assert client.get('/api/status', headers={'Origin': 'https://attacker.example'}).status_code == 403
    assert client.get('/api/status', headers={'Sec-Fetch-Site': 'cross-site'}).status_code == 403
    assert client.get('/api/status', headers={'Origin': 'http://testserver'}).status_code == 200
    assert client.post('/api/sessions', json={'mode': 'live'}).status_code == 409
    assert client.post('/api/sessions', json={'unexpected': True}).status_code == 422
    identity = new_session(client)
    assert client.post(f'/api/sessions/{identity}/turns', json={'prompt': '   '}).status_code == 422
    assert client.get('/api/sessions/not-a-session').status_code == 404


def test_sdk_approval_denial_and_monotonic_event_contract(client):
    identity = new_session(client)
    assert client.post(f'/api/sessions/{identity}/turns', json={'prompt': '审批拒绝实验'}).status_code == 202
    waiting = wait_for(client, identity, lambda state: state['status'] == 'waiting_permission')
    request = waiting['pending_permissions'][0]
    assert waiting['sdk_session_id']
    assert client.post(f'/api/sessions/{identity}/turns', json={'prompt': '并发请求'}).status_code == 409
    assert client.post(f'/api/sessions/{identity}/permissions/wrong', json={'outcome': 'deny'}).status_code == 409
    response = client.post(f"/api/sessions/{identity}/permissions/{request['request_id']}", json={'outcome': 'deny'})
    assert response.status_code == 200
    done = wait_for(client, identity, lambda state: state['status'] == 'completed')
    assert not done['pending_permissions']
    assert not done['files']
    assert done['result']['status'] == 'completed'
    results = tool_results(done, 'run_tests')
    assert len(results) == 1 and results[0]['is_error']
    assert results[0]['error_code'] == 'permission_user_denied'
    kinds = {event['kind'] for event in done['events']}
    assert {'user_message_created', 'assistant_text_delta', 'tool_call_started',
            'permission_request_created', 'permission_request_resolved',
            'tool_result_received', 'turn_completed', 'lab_result'} <= kinds
    sequence = [event['sequence'] for event in done['events']]
    assert sequence == list(range(1, len(sequence) + 1))
    sdk_events = [event for event in done['events'] if 'sdk_sequence' in event]
    assert all(event['session_id'] == done['sdk_session_id'] for event in sdk_events)
    assert any(event['run_id'] for event in sdk_events)
    # 事件转换结果须可完整 JSON 序列化；供应商未提供 token 时不能杜撰用量。
    json.dumps(done, ensure_ascii=False)
    assert done['result']['usage']['input_tokens'] is None
    assert client.post(f"/api/sessions/{identity}/permissions/{request['request_id']}", json={'outcome': 'allow'}).status_code == 409


def test_generation_no_docker_never_claims_success(client):
    identity = new_session(client)
    client.post(f'/api/sessions/{identity}/turns', json={'prompt': '构建 Todo 后端'})
    done = resolve_all_until_done(client, identity, 'allow')
    assert done['status'] == 'completed'
    assert {file['path'] for file in done['files']} == {'app.py', 'tests/test_api.py', 'README.md'}
    results = tool_results(done, 'run_tests')
    assert len(results) == 1 and results[0]['error_code'] == 'isolation_unavailable'
    assert '没有执行生成代码' in done['result']['text']
    preview = client.get(f'/api/sessions/{identity}/file', params={'path': 'app.py'}).json()
    assert 'return self.reply(201, item)' in preview['content']
    assert preview['baseline'] == '' and '+++ b/app.py' in preview['diff']


def test_normal_completion_consumes_followup_queue(client):
    identity = new_session(client)
    client.post(f'/api/sessions/{identity}/turns', json={'prompt': '第一轮审批'})
    wait_for(client, identity, lambda state: state['status'] == 'waiting_permission')
    assert client.post(f'/api/sessions/{identity}/queue', json={'prompt': '第二轮审批'}).status_code == 202
    done = resolve_all_until_done(client, identity)
    assert done['status'] == 'completed' and done['queue'] == []
    users = [message['content'] for message in done['messages'] if message['role'] == 'user']
    assert users == ['第一轮审批', '第二轮审批']
    assert len(tool_results(done, 'run_tests')) == 2


def test_stop_preserves_queue_and_explicit_resume(client):
    identity = new_session(client)
    client.post(f'/api/sessions/{identity}/turns', json={'prompt': '慢速停止实验'})
    wait_for(client, identity, lambda state: any(event['kind'] == 'assistant_text_delta' for event in state['events']))
    assert client.post(f'/api/sessions/{identity}/queue', json={'prompt': '恢复后审批'}).status_code == 202
    stopped = client.post(f'/api/sessions/{identity}/stop')
    assert stopped.status_code == 200
    state = detail(client, identity)
    assert state['status'] == 'cancelled' and state['queue_paused']
    assert not tool_results(state)
    assert len(state['queue']) == 1
    assert [message['content'] for message in state['messages'] if message['role'] == 'user'] == ['慢速停止实验']
    assert any(event['kind'] == 'turn_cancelled' for event in state['events'])
    assert client.post(f'/api/sessions/{identity}/resume').status_code == 200
    done = resolve_all_until_done(client, identity)
    assert done['status'] == 'completed' and not done['queue']
    assert [message['content'] for message in done['messages'] if message['role'] == 'user'] == ['慢速停止实验', '恢复后审批']


def test_shutdown_restart_restores_sdk_history_and_paused_queue(lab_root, monkeypatch):
    monkeypatch.setattr(LabManager, '_probe_docker', lambda _self: False)
    with TestClient(create_app(lab_root)) as first:
        identity = new_session(first)
        first.post(f'/api/sessions/{identity}/turns', json={'prompt': '慢速任务'})
        wait_for(first, identity, lambda state: any(event['kind'] == 'assistant_text_delta' for event in state['events']))
        first.post(f'/api/sessions/{identity}/queue', json={'prompt': '重启后审批'})
        sdk_identity = detail(first, identity)['sdk_session_id']
    with TestClient(create_app(lab_root)) as second:
        restored = detail(second, identity)
        assert restored['sdk_session_id'] == sdk_identity
        assert restored['status'] == 'cancelled' and len(restored['queue']) == 1
        previous_sequence = restored['events'][-1]['sequence']
        second.post(f'/api/sessions/{identity}/resume')
        done = resolve_all_until_done(second, identity)
        assert done['status'] == 'completed' and done['sdk_session_id'] == sdk_identity
        assert [message['content'] for message in done['messages'] if message['role'] == 'user'] == ['慢速任务', '重启后审批']
        assert done['events'][-1]['sequence'] > previous_sequence
        sequence = [event['sequence'] for event in done['events']]
        assert sequence == list(range(1, len(sequence) + 1))


def test_pending_approval_shutdown_does_not_deadlock(lab_root, monkeypatch):
    monkeypatch.setattr(LabManager, '_probe_docker', lambda _self: False)
    with TestClient(create_app(lab_root)) as first:
        identity = new_session(first)
        first.post(f'/api/sessions/{identity}/turns', json={'prompt': '审批等待关闭'})
        wait_for(first, identity, lambda state: state['status'] == 'waiting_permission')
    with TestClient(create_app(lab_root)) as second:
        restored = detail(second, identity)
        assert restored['status'] == 'cancelled'
        assert not restored['pending_permissions']
        assert any(event['kind'] == 'permission_request_closed' for event in restored['events'])


@pytest.mark.parametrize('path', ['../outside.txt', '/etc/passwd', 'C:/outside.txt',
    'C:\\outside.txt', '//server/share', '.lancher/session.json', 'nested/.hidden',
    './app.py', 'a/../app.py', 'a//b', 'CON.txt', 'NUL', 'file.py:stream', 'trailing.', 'x\\y'])
def test_file_api_rejects_forbidden_paths(client, path):
    identity = new_session(client)
    assert client.get(f'/api/sessions/{identity}/file', params={'path': path}).status_code == 403


def test_hardlinks_and_hidden_files_cannot_be_read(client, tmp_path):
    identity = new_session(client)
    workspace = Path(detail(client, identity)['workspace'])
    hidden = workspace / '.hidden'
    hidden.write_text('不可展示', encoding='utf-8')
    outside = tmp_path / 'outside.txt'
    outside.write_text('外部内容', encoding='utf-8')
    os.link(outside, workspace / 'linked.txt')
    assert client.get(f'/api/sessions/{identity}/file', params={'path': 'linked.txt'}).status_code == 403
    assert '.hidden' not in {row['path'] for row in client.get(f'/api/sessions/{identity}/files').json()['files']}
    with pytest.raises(ValueError, match='硬链接'):
        resolve_lab_path(workspace, 'linked.txt')
    with pytest.raises(ValueError):
        list_workspace_files(workspace)


async def test_events_replay_from_cursor(lab_root, monkeypatch):
    monkeypatch.setattr(LabManager, '_probe_docker', lambda _self: False)
    manager = LabManager(lab_root)
    await manager.start()
    try:
        session = await manager.create()
        manager.emit(session, {'kind': 'lab_log', 'text': 'first'})
        cursor = session.events[-1]['sequence']
        manager.emit(session, {'kind': 'lab_log', 'text': 'second'})
        manager.emit(session, {'kind': 'lab_log', 'text': 'third'})
        stream = manager.events_after(session, cursor)
        first = await asyncio.wait_for(anext(stream), 1)
        second = await asyncio.wait_for(anext(stream), 1)
        await stream.aclose()
        assert [first['text'], second['text']] == ['second', 'third']
        assert [first['sequence'], second['sequence']] == [cursor + 1, cursor + 2]
    finally:
        await manager.close()


async def test_run_tests_no_host_fallback(tmp_path, monkeypatch):
    async def forbidden(*_args, **_kwargs):
        raise AssertionError('Docker 不可用时不允许创建任何宿主执行进程')
    monkeypatch.setattr(asyncio, 'create_subprocess_exec', forbidden)
    result = await RunTests(tmp_path, False, lambda _text: None).execute({}, None)
    assert result.is_error and result.error_code == 'isolation_unavailable'
    assert not (tmp_path.parent / '.sandbox').exists()


async def test_docker_command_uses_copy_and_removes_container(tmp_path, monkeypatch):
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    (workspace / 'app.py').write_text('visible = True', encoding='utf-8')
    (workspace / '.hidden').write_text('private', encoding='utf-8')
    commands, snapshots, logs = [], [], []

    class Output:
        def __init__(self):
            self.sent = False
        async def read(self, _size):
            if self.sent:
                return b''
            self.sent = True
            return b'Ran 4 tests\nOK\n'

    class Process:
        def __init__(self, run=False):
            self.stdout = Output() if run else None
            self.returncode = None
        async def wait(self):
            self.returncode = 0
            return 0
        async def communicate(self):
            self.returncode = 0
            return b'', b''
        def kill(self):
            self.returncode = -9

    async def fake_subprocess(*command, **_kwargs):
        commands.append(command)
        if command[1] == 'run':
            mount = command[command.index('--mount') + 1]
            snapshot = Path(mount.split('source=', 1)[1].split(',target=', 1)[0])
            snapshots.append(snapshot)
            assert snapshot != workspace and snapshot.is_relative_to(workspace.parent / '.sandbox')
            assert (snapshot / 'app.py').read_text(encoding='utf-8') == 'visible = True'
            assert not (snapshot / '.hidden').exists()
            return Process(True)
        assert command[1:3] in {('rm', '-f'), ('ps', '-aq')}
        return Process()

    monkeypatch.setattr('lab.tools.shutil.which', lambda _name: 'docker')
    monkeypatch.setattr(asyncio, 'create_subprocess_exec', fake_subprocess)
    result = await RunTests(workspace, True, logs.append).execute({}, None)
    assert not result.is_error
    command = commands[0]
    for flag in ('--read-only', '--cap-drop', '--security-opt', '--memory', '--cpus', '--pids-limit'):
        assert flag in command
    assert command[command.index('--network') + 1] == 'none'
    assert command[-8:] == ('python:3.14-slim', 'python', '-m', 'unittest', 'discover', '-s', 'tests', '-v')
    assert next(item for item in commands if item[1] == 'rm')[3] == command[command.index('--name') + 1]
    assert commands[-1][1:3] == ('ps', '-aq')
    assert command[command.index('--mount') + 1].endswith(',readonly')
    assert all(not path.exists() for path in snapshots)
    assert any('OK' in text for text in logs)




def test_sdk_repair_reads_and_rewrites_after_mocked_failed_tests(client, monkeypatch):
    # 只模拟 Docker 工具的失败/成功边界；SDK 工具编排、文件读写和审批真实运行。
    outputs = []

    async def mocked_run(tool, _arguments, _context):
        source = (tool.workspace / 'app.py').read_text(encoding='utf-8')
        if '\n        return self.reply(200, item)\n' in source:
            outputs.append('FAILED')
            return RunTests._result('tests_failed', '模拟隔离测试失败',
                                    exit_code=1, output='FAILED: 200 != 201')
        outputs.append('OK')
        return RunTests._result(None, '模拟隔离测试通过', exit_code=0, output='Ran 4 tests\nOK')

    monkeypatch.setattr(RunTests, 'execute', mocked_run)
    identity = new_session(client)
    client.post(f'/api/sessions/{identity}/turns', json={'prompt': '故意失败然后修复后端'})
    done = resolve_all_until_done(client, identity, 'allow')
    assert outputs == ['FAILED', 'OK']
    tests = tool_results(done, 'run_tests')
    assert tests[0]['is_error'] and not tests[1]['is_error']
    assert len(tool_results(done, 'write_file')) == 4
    assert len([event for event in done['events'] if event['kind'] == 'tool_call_started'
                and event['tool_call']['tool_name'] == 'read_file'
                and event['tool_call']['arguments']['path'] == 'app.py']) == 2


def test_parallel_session_limit_returns_429(client):
    identities = [new_session(client, f'并行 {index}') for index in range(5)]
    for identity in identities[:4]:
        assert client.post(f'/api/sessions/{identity}/turns', json={'prompt': '慢速任务'}).status_code == 202
    assert client.post(f'/api/sessions/{identities[4]}/turns', json={'prompt': '额外任务'}).status_code == 429
    for identity in identities[:4]:
        assert client.post(f'/api/sessions/{identity}/stop').status_code == 200


async def test_docker_cancellation_finishes_container_and_snapshot_cleanup(tmp_path, monkeypatch):
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    (workspace / 'app.py').write_text('safe = True', encoding='utf-8')
    launched = asyncio.Event()
    commands = []
    snapshots = []

    class PendingOutput:
        async def read(self, _size):
            await asyncio.Event().wait()

    class Process:
        def __init__(self, is_run):
            self.is_run = is_run
            self.stdout = PendingOutput() if is_run else None
            self.returncode = None
            self.killed = False
        async def wait(self):
            self.returncode = -9 if self.killed else 0
            return self.returncode
        async def communicate(self):
            self.returncode = 0
            return b'', b''
        def kill(self):
            self.killed = True
            self.returncode = -9

    async def fake_subprocess(*command, **_kwargs):
        commands.append(command)
        if command[1] == 'run':
            mount = command[command.index('--mount') + 1]
            snapshots.append(Path(mount.split('source=', 1)[1].split(',target=', 1)[0]))
            launched.set()
            return Process(True)
        assert command[1:3] in {('rm', '-f'), ('ps', '-aq')}
        return Process(False)

    monkeypatch.setattr('lab.tools.shutil.which', lambda _name: 'docker')
    monkeypatch.setattr(asyncio, 'create_subprocess_exec', fake_subprocess)
    task = asyncio.create_task(RunTests(workspace, True, lambda _text: None).execute({}, None))
    await asyncio.wait_for(launched.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 3)
    assert any(command[1:3] == ('rm', '-f') for command in commands)
    assert commands[-1][1:3] == ('ps', '-aq')
    assert all(not path.exists() for path in snapshots)



def test_demo_ignores_sdk_host_updates_when_selecting_user_prompt():
    from lab.demo import DemoProvider
    from lancher_code.contracts.messages import ChatRequest, ConversationMessage
    request = ChatRequest(model='test', messages=[
        ConversationMessage.text_message('user', '故意失败然后修复后端'),
        ConversationMessage.text_message('user', '<host_update epoch="2">主机状态增量</host_update>'),
    ])
    assert DemoProvider._turn(request)[0] == '故意失败然后修复后端'


def test_sdk_approval_cannot_bypass_confined_file_adapter(client):
    identity = new_session(client)
    workspace = Path(detail(client, identity)['workspace'])
    client.post(f'/api/sessions/{identity}/turns', json={'prompt': '越界验证'})
    done = resolve_all_until_done(client, identity, 'allow')
    results = tool_results(done, 'write_file')
    assert len(results) == 1 and results[0]['is_error']
    assert results[0]['error_code'] == 'lab_path_denied'
    assert not (workspace.parent / 'outside.txt').exists()
    assert not done['files']




async def test_docker_unconfirmed_cleanup_reports_error_and_preserves_snapshot(tmp_path, monkeypatch):
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    (workspace / 'app.py').write_text('safe = True', encoding='utf-8')
    snapshots = []

    class Output:
        async def read(self, _size):
            return b''

    class Process:
        def __init__(self):
            self.returncode = None
            self.stdout = Output()
        async def wait(self):
            self.returncode = 0
            return 0
        async def communicate(self):
            self.returncode = 0
            return b'still-running-container\n', b''
        def kill(self):
            self.returncode = -9

    async def fake_subprocess(*command, **_kwargs):
        if command[1] == 'run':
            mount = command[command.index('--mount') + 1]
            snapshots.append(Path(mount.split('source=', 1)[1].split(',target=', 1)[0]))
        return Process()

    monkeypatch.setattr('lab.tools.shutil.which', lambda _name: 'docker')
    monkeypatch.setattr(asyncio, 'create_subprocess_exec', fake_subprocess)
    result = await RunTests(workspace, True, lambda _text: None).execute({}, None)
    assert result.is_error and result.error_code == 'sandbox_cleanup_failed'
    assert snapshots and all(path.exists() for path in snapshots)
    # 此处全部为模拟进程；验证保留后，主动清理没有实际挂载的测试夹具。
    import shutil
    for snapshot in snapshots:
        assert snapshot.resolve().is_relative_to(tmp_path.resolve())
        shutil.rmtree(snapshot)



def test_incremental_text_keeps_complete_snapshot_after_restart(lab_root, monkeypatch):
    monkeypatch.setattr(LabManager, '_probe_docker', lambda _self: False)
    with TestClient(create_app(lab_root)) as first:
        identity = new_session(first)
        first.post(f'/api/sessions/{identity}/turns', json={'prompt': '审批文本持久化验证'})
        complete = resolve_all_until_done(first, identity)
        deltas = [event for event in complete['events'] if event['kind'] == 'assistant_text_delta']
        assert deltas and all(event['message'] is None for event in deltas)
        completed = [event for event in complete['events'] if event['kind'] == 'assistant_message_completed']
        assert completed and completed[-1]['message']
        final_text = completed[-1]['message']['content']
        assert final_text and final_text in ''.join(event['text'] or '' for event in deltas)
        snapshot = complete['messages']
        stored_events = [json.loads(line) for line in
            (lab_root / 'data' / 'sessions' / identity / 'events.jsonl').read_text(encoding='utf-8').splitlines()]
        assert [event['text'] for event in stored_events if event['kind'] == 'assistant_text_delta'] == [event['text'] for event in deltas]
    with TestClient(create_app(lab_root)) as second:
        restored = detail(second, identity)
        assert restored['messages'] == snapshot
        assert any(message['content'] == final_text for message in restored['messages'])


async def test_thinking_progress_drops_repeated_large_snapshots_but_keeps_completion(lab_root, monkeypatch):
    from datetime import datetime, timezone
    from lancher_code.agent.events import TurnEvent
    from lancher_code.sessions.models import SessionMessage, ThinkingTrace, TraceEntry
    monkeypatch.setattr(LabManager, '_probe_docker', lambda _self: False)
    manager = LabManager(lab_root)
    await manager.start()
    try:
        session = await manager.create()
        saves = []
        monkeypatch.setattr(manager, 'save', lambda current: saves.append(current.id))
        large_thinking = '推理内容' * 50_000
        message = SessionMessage(id='thinking-message', role='assistant', content='', status='streaming',
            timestamp=datetime.now(timezone.utc), trace=ThinkingTrace([TraceEntry(kind='thinking', text=large_thinking)]))
        for sequence in range(1, 101):
            manager.on_sdk_event(session, TurnEvent(kind='progress_updated', message=message,
                progress_message='思考中', session_id='sdk-progress', sequence=sequence))
        progress = [event for event in session.events if event['kind'] == 'progress_updated']
        assert len(progress) == 1 and progress[0]['message'] is None
        assert len(json.dumps(progress[0], ensure_ascii=False)) < 4000
        assert '推理内容' not in json.dumps(progress[0], ensure_ascii=False)
        assert saves == []
        manager.on_sdk_event(session, TurnEvent(kind='assistant_text_delta', message=message,
            text='完整正文', session_id='sdk-progress', sequence=101))
        assert session.events[-1]['text'] == '完整正文' and session.events[-1]['message'] is None
        assert saves == []
        message.content = '完整正文'
        message.status = 'complete'
        manager.on_sdk_event(session, TurnEvent(kind='assistant_message_completed', message=message,
            session_id='sdk-progress', sequence=102))
        final = session.events[-1]
        assert final['message']['content'] == '完整正文'
        assert final['message']['trace']['entries'][0]['text'] == large_thinking
        assert message.trace.entries[0].text == large_thinking
        assert saves == [session.id]
        assert [event['sequence'] for event in session.events] == list(range(1, len(session.events) + 1))
    finally:
        await manager.close()

