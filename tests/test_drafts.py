"""空白草稿只在内存，首次输入接受后进入正式 SDK/Web 生命周期。"""
from __future__ import annotations

import threading
from uuid import uuid4

from fastapi.testclient import TestClient

from provider_helpers import Reply
from test_integration import action, chat, complete, detail, project, request, submit, wait


def _app(isolated, provider):
    from webui.api import create_app
    return create_app(root=isolated[0], user_home=isolated[1],
                      provider_factory=lambda _: provider, enable_mcp=False)


def _registered(client):
    async def read():
        return client.app.state.manager.store.load('chats')
    return client.portal.call(read)


def _sessions(workspace):
    directory = workspace / '.lancher' / 'sessions'
    return list(directory.iterdir()) if directory.exists() else []


def test_blank_draft_controls_and_reading_never_register_history(client, isolated, provider):
    _, home, workspace = isolated
    skill = home / '.lancher' / 'skills' / 'review'
    skill.mkdir(parents=True)
    (skill / 'SKILL.md').write_text('---\nname: review\ndescription: 草稿验收\n---\n仅测试指南。\n', encoding='utf-8')
    project_id = project(client, workspace)
    identity = chat(client, project_id)
    first = detail(client, identity)
    assert first['draft'] and first['sdk_session_id'] is None and first['messages'] == []
    for text in ('/status', '/model test/two', '/access full', '/plan', '/skills list', '/settings'):
        request(client, 'POST', f'/api/chats/{identity}/commands', json={'text': text})
    action(client, identity, 'skills_show', name='review')
    action(client, identity, 'skills_disable', name='review')
    action(client, identity, 'skills_enable', name='review')
    action(client, identity, 'skills_reload')
    patched = request(client, 'PATCH', f'/api/chats/{identity}',
                      json={'title': '保留空白草稿', 'phase': 'discuss', 'access': 'project', 'model_ref': 'test/one'})
    assert patched['draft'] and patched['phase'] == 'discuss' and patched['model_ref'] == 'test/one'
    assert detail(client, identity)['messages'] == []
    assert provider.requests == [] and _registered(client) == {} and _sessions(workspace) == []
    assert request(client, 'GET', f'/api/projects/{project_id}/impact')['conversation_count'] == 0
    assert client.post(f'/api/chats/{identity}/turns', json={'prompt': ' '}).status_code == 422
    assert client.post(f'/api/chats/{identity}/turns', json={'prompt': '无效附件', 'attachments': ['missing.txt']}).status_code == 404
    assert client.patch(f'/api/chats/{identity}', json={'phase': 'unknown'}).status_code == 400
    assert detail(client, identity)['draft'] and _registered(client) == {}
    action(client, identity, 'release')
    assert _sessions(workspace) == [] and _registered(client) == {}

    async def replay():
        return client.app.state.manager.store.events_after(0)
    events = [event for event in client.portal.call(replay) if event.get('chat_id') == identity]
    assert events and all(event['kind'] in {'chat_state', 'capabilities_updated', 'mcp_progress_updated', 'processes_updated'} for event in events)
    assert all('message' not in event and 'tool_call' not in event for event in events)


def test_first_input_promotes_while_queued_and_cancelled_task_survives_restart(isolated, provider):
    workspace = isolated[2]
    gate = threading.Event()
    provider.plans['占用项目前台'] = [Reply(text='完成', gate=gate)]
    with TestClient(_app(isolated, provider), raise_server_exceptions=False) as client:
        project_id = project(client, workspace)
        running, queued = chat(client, project_id), chat(client, project_id)
        assert _registered(client) == {}
        submit(client, running, '占用项目前台')
        wait(client, running, lambda _: bool(provider.requests))
        accepted = submit(client, queued, '排队时就成为正式对话')
        assert accepted['chat']['draft'] is False and accepted['chat']['status'] == 'queued'
        assert accepted['chat']['sdk_session_id'] is None
        assert accepted['chat']['first_turn_accepted_at']
        assert set(_registered(client)) == {running, queued}
        assert request(client, 'GET', f'/api/projects/{project_id}/impact')['conversation_count'] == 2
        request(client, 'POST', f'/api/chats/{queued}/stop', json={'scope': 'turn'})
        request(client, 'POST', f'/api/chats/{running}/stop', json={'scope': 'turn'})
        assert detail(client, queued)['status'] == 'cancelled'
        assert not detail(client, queued)['draft']
        assert not any(row['prompt'] == '排队时就成为正式对话' for row in provider.requests)
    with TestClient(_app(isolated, provider), raise_server_exceptions=False) as restored:
        saved = detail(restored, queued)
        assert saved['draft'] is False and saved['sdk_session_id'] is None
        assert saved['pending_task']['prompt'] == '排队时就成为正式对话'
        action(restored, queued, 'queue_resume')
        final = complete(restored, queued)
        assert final['status'] == 'completed' and final['sdk_session_id'] and not final['draft']


def test_draft_id_restore_is_safe_and_first_failure_still_registers(isolated, provider):
    from lancher_code.errors import ProviderRequestError
    from lancher_code.contracts.messages import StreamEvent

    original = provider.stream_chat
    async def failed_stream(outgoing):
        if provider.prompt(outgoing) == '供应商失败仍保存首条任务':
            yield StreamEvent(kind='message_start')
            raise ProviderRequestError('专用 fixture 供应商失败。')
        async for event in original(outgoing):
            yield event
    provider.stream_chat = failed_stream
    draft_id, blank_id = uuid4().hex, uuid4().hex
    with TestClient(_app(isolated, provider), raise_server_exceptions=False) as client:
        project_id = project(client, isolated[2])
        other = isolated[2].parent / 'other-project'
        other.mkdir()
        other_id = project(client, other)
        payload = {'project_id': project_id, 'draft_id': draft_id.upper(), 'title': '恢复的草稿',
                   'phase': 'plan', 'access': 'full', 'model_ref': 'test/two'}
        created = request(client, 'POST', '/api/chats', json=payload)
        assert created['id'] == draft_id and created['draft'] and created['phase'] == 'plan'
        duplicate = request(client, 'POST', '/api/chats', json={**payload, 'title': '不能覆盖现存草稿'})
        assert duplicate == created
        assert client.post('/api/chats', json={**payload, 'project_id': other_id}).status_code == 409
        assert client.post('/api/chats', json={'project_id': project_id, 'draft_id': 'bad-id'}).status_code == 422
        accepted = submit(client, draft_id, '供应商失败仍保存首条任务')
        assert accepted['chat']['draft'] is False
        failed = complete(client, draft_id)
        assert failed['status'] == 'failed' and failed['sdk_session_id'] and not failed['draft']
        assert client.post('/api/chats', json=payload).status_code == 409
        assert client.post('/api/chats', json={**payload, 'draft_id': failed['sdk_session_id']}).status_code == 409
        blank = request(client, 'POST', '/api/chats', json={'project_id': project_id, 'draft_id': blank_id,
            'title': '未提交的新对话', 'phase': 'discuss', 'access': 'full', 'model_ref': 'test/two'})
        assert blank['draft'] and blank_id not in _registered(client)
    with TestClient(_app(isolated, provider), raise_server_exceptions=False) as restored:
        assert restored.get(f'/api/chats/{blank_id}').status_code == 404
        recreated = request(restored, 'POST', '/api/chats', json={'project_id': project_id, 'draft_id': blank_id,
            'title': '未提交的新对话', 'phase': 'discuss', 'access': 'full', 'model_ref': 'test/two'})
        assert recreated['id'] == blank_id and recreated['draft']
        assert (recreated['phase'], recreated['access'], recreated['model_ref']) == ('discuss', 'full', 'test/two')
        assert blank_id not in _registered(restored) and not detail(restored, draft_id)['draft']


def test_only_truly_empty_legacy_metadata_is_migrated_to_memory(isolated, provider):
    from webui.store import Store
    with TestClient(_app(isolated, provider), raise_server_exceptions=False) as client:
        project_id = project(client, isolated[2])
        native = chat(client, project_id)
        action(client, native, 'phase', phase='plan')
        submit(client, native, '既有计划会话')
        assert complete(client, native)['sdk_session_id']
    store = Store(isolated[0] / 'data' / 'webui.sqlite3')
    native_row = store.load('chats')[native]
    native_row.pop('draft', None)
    native_row.pop('first_turn_accepted_at', None)
    store.put('chats', native, native_row)
    base = {**native_row, 'sdk_session_id': None, 'result': None, 'phase': 'plan', 'status': 'idle'}
    empty_id, pending_id, baseline_id = uuid4().hex, uuid4().hex, uuid4().hex
    store.put('chats', empty_id, {**base, 'id': empty_id, 'title': '旧版未发消息的空白'})
    store.put('chats', pending_id, {**base, 'id': pending_id, 'status': 'queued',
        'pending_task': {'kind': 'turn', 'chat_id': pending_id, 'operation_id': uuid4().hex, 'prompt': '已接受但尚未运行'}})
    store.put('chats', baseline_id, {**base, 'id': baseline_id})
    store.file_baseline(baseline_id, 'previous.txt', '已有修改基线')
    store.close()

    with TestClient(_app(isolated, provider), raise_server_exceptions=False) as client:
        migrated = detail(client, empty_id)
        assert migrated['draft'] and migrated['sdk_session_id'] is None
        saved = _registered(client)
        assert empty_id not in saved
        assert set(saved) == {native, pending_id, baseline_id}
        assert all(row['draft'] is False for row in saved.values())
        assert detail(client, pending_id)['status'] == 'interrupted'
        assert detail(client, native)['sdk_session_id'] == native_row['sdk_session_id']
        assert request(client, 'GET', f'/api/projects/{project_id}/impact')['conversation_count'] == 3


def test_first_queue_input_on_draft_is_a_recoverable_formal_task(client, isolated, provider):
    identity = chat(client, project(client, isolated[2]))
    accepted = action(client, identity, 'queue_add', text='新草稿的首条排队输入', delivery='follow_up')
    assert accepted['accepted'] and not accepted['chat']['draft']
    final = complete(client, identity)
    assert final['status'] == 'completed' and final['sdk_session_id']
    assert [item['content'] for item in final['messages'] if item['role'] == 'user'] == ['新草稿的首条排队输入']