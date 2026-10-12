"""归档设置入口沿用真实 SDK 历史；恢复只改变 Web 导航覆盖。"""
from __future__ import annotations

import threading

from fastapi.testclient import TestClient

from provider_helpers import Reply
from test_integration import chat, complete, detail, project, request, submit, wait


def _app(isolated, provider):
    from webui.api import create_app
    return create_app(root=isolated[0], user_home=isolated[1],
                      provider_factory=lambda _: provider, enable_mcp=False)


def _native_info(workspace, session_id):
    from lancher_code.sessions.repository import ProjectSessionRepository
    return next(row for row in ProjectSessionRepository(workspace).list_sessions().items
                if row.session_id == session_id)


def test_archive_read_restore_and_restart_preserve_native_history_and_web_override(isolated, provider):
    from lancher_code.sessions.repository import ProjectSessionRepository
    workspace = isolated[2]
    with TestClient(_app(isolated, provider), raise_server_exceptions=False) as client:
        identity = chat(client, project(client, workspace), '真实归档历史')
        submit(client, identity, '只在临时项目保存归档验收记录')
        initial = complete(client, identity)
        assert initial['status'] == 'completed'
        session_id = initial['sdk_session_id']
        event_path = ProjectSessionRepository(workspace).paths(session_id).events
        before = event_path.read_bytes()
        archived = request(client, 'PATCH', f'/api/chats/{identity}', json={'archived': True})
        assert archived['archived'] and not archived.get('archive_override', False)
        assert _native_info(workspace, session_id).archived
        after_archive = event_path.read_bytes()
        assert after_archive.startswith(before) and after_archive.count(b'session.archived') == 1
        assert client.post(f'/api/chats/{identity}/turns', json={'prompt': '归档中禁止追加'}).status_code == 409
        for _ in range(2):
            opened = detail(client, identity)
            assert opened['archived'] and opened['messages'] == initial['messages']
            rows = request(client, 'GET', '/api/bootstrap')['chats']
            assert next(row for row in rows if row['id'] == identity)['archived']
        assert event_path.read_bytes() == after_archive
        restored = request(client, 'PATCH', f'/api/chats/{identity}', json={'archived': False})
        assert restored['archive_override'] is False and not restored['archived']
        assert _native_info(workspace, session_id).archived
        assert event_path.read_bytes() == after_archive, 'Web 恢复不能伪造 SDK unarchive 事件。'
    with TestClient(_app(isolated, provider), raise_server_exceptions=False) as restarted:
        rows = request(restarted, 'GET', '/api/bootstrap')['chats']
        assert not next(row for row in rows if row['id'] == identity)['archived']
        restored = detail(restarted, identity)
        assert restored['sdk_session_id'] == session_id and restored['messages'] == initial['messages']
        assert event_path.read_bytes() == after_archive
        submit(restarted, identity, 'Web 恢复后沿用同一 SDK UUID')
        continued = complete(restarted, identity)
        assert continued['status'] == 'completed' and continued['sdk_session_id'] == session_id
        assert [row['content'] for row in continued['messages'] if row['role'] == 'user'] == [
            '只在临时项目保存归档验收记录', 'Web 恢复后沿用同一 SDK UUID']
        assert event_path.read_bytes().count(b'session.archived') == 1
        assert _native_info(workspace, session_id).archived


def test_busy_archive_is_rejected_without_interrupting_real_sdk_turn(client, isolated, provider):
    identity = chat(client, project(client, isolated[2]))
    gate = threading.Event()
    provider.plans['归档忙时闸门'] = [Reply(text='原任务正常完成', gate=gate)]
    try:
        submit(client, identity, '归档忙时闸门')
        wait(client, identity, lambda row: bool(provider.requests) and row['status'] == 'running')
        rejected = client.patch(f'/api/chats/{identity}', json={'archived': True})
        assert rejected.status_code == 409
        current = detail(client, identity)
        assert not current['archived'] and current['status'] == 'running'
        assert not _native_info(isolated[2], current['sdk_session_id']).archived
    finally:
        gate.set()
    finished = complete(client, identity)
    assert finished['status'] == 'completed' and finished['result']['text'].endswith('原任务正常完成')
    assert request(client, 'PATCH', f'/api/chats/{identity}', json={'archived': True})['archived']
