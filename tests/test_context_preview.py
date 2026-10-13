"""历史上下文估算通过只读 SDK 投影完成，不持会话写入锁。"""
from __future__ import annotations

import pytest

from provider_helpers import Reply
from test_integration import action, chat, complete, detail, project, submit


def configured_context_window(isolated):
    _, home, _ = isolated
    config_path = home / '.lancher' / 'lancher.yaml'
    config_text = config_path.read_text(encoding='utf-8')
    config_text = config_text.replace('model_name: fixture-one', 'model_name: fixture-one\n        context_window: 32768')
    config_path.write_text(config_text, encoding='utf-8')
    return 32768


def native_context_turn(client, isolated, provider):
    workspace = isolated[2]
    (workspace / 'readme.txt').write_text('历史上下文中的真实工程文本。\n', encoding='utf-8')
    provider.plans['上下文预览任务'] = [
        Reply(tools=[('read_file', {'path': 'readme.txt'})]),
        Reply(tools=[('write_file', {'path': 'created.txt', 'content': '原生文件工具已经完成。\n'})]),
        Reply(text='完整上下文应包含这次文件读取、写入和最终答复。'),
    ]
    identity = chat(client, project(client, workspace))
    submit(client, identity, '上下文预览任务')
    state = complete(client, identity)
    assert state['status'] == 'completed'
    return identity, state


def test_released_native_session_context_matches_live_estimate(client, isolated, provider, monkeypatch):
    import webui.context_preview as preview
    requests = []
    estimate = preview.estimate_request

    def capture(request, state):
        requests.append((request, state))
        return estimate(request, state)

    monkeypatch.setattr(preview, 'estimate_request', capture)
    expected_window = configured_context_window(isolated)
    identity, live = native_context_turn(client, isolated, provider)
    assert live['context']['window'] == expected_window and live['context']['tokens'] > 0
    action(client, identity, 'release')
    saved = detail(client, identity)
    assert saved['context']['snapshot'] is True
    assert saved['context']['window'] == expected_window and saved['context']['tokens'] > 0
    assert saved['context']['source'] in {'estimated', 'usage_calibrated'}
    # 只允许 SDK 请求前缀的轻微增量；不能用整个会话累计输入替代当前上下文。
    assert abs(saved['context']['tokens'] - live['context']['tokens']) <= max(256, live['context']['tokens'] * 0.20)
    assert saved['usage'] == live['usage']
    outgoing, context = requests[-1]
    assert outgoing.shared_system_count == context.prefix_state['shared_system_count'] > 0
    repeated = detail(client, identity)
    assert repeated['context'] == saved['context'] and repeated['usage'] == saved['usage']


def test_context_detail_is_read_only_while_tui_owns_native_uuid(client, isolated, provider):
    from lancher_code.agent.skills import SkillsService
    from lancher_code.config.loader import load_config
    from lancher_code.errors import ConfigError
    from lancher_code.permissions.storage import PermissionStorage
    from lancher_code.sdk import create_agent
    from lancher_code.sessions.repository import ProjectSessionRepository
    from lancher_code.sessions.storage import SessionBusyError
    _, home, workspace = isolated
    expected_window = configured_context_window(isolated)
    identity, state = native_context_turn(client, isolated, provider)
    session_id = state['sdk_session_id']
    action(client, identity, 'release')

    def create_tui_agent():
        return create_agent(load_config(home / '.lancher' / 'lancher.yaml').to_agent_config(),
            cwd=workspace, provider_factory=lambda _config: provider, enable_mcp=False,
            permission_storage=PermissionStorage(project_rules_path=workspace / '.lancher' / 'permissions.yaml',
                user_rules_path=home / '.lancher' / 'permissions.yaml'),
            skills_service=SkillsService(workspace, user_root=home))

    async def acquire_tui():
        agent = create_tui_agent()
        await agent.ready()
        agent.resume_session(session_id)
        return agent

    tui = client.portal.call(acquire_tui)
    event_path = ProjectSessionRepository(workspace).paths(session_id).events
    before = event_path.read_bytes()
    try:
        async def confirm_actual_writer_lock():
            competitor = create_tui_agent()
            try:
                await competitor.ready()
                with pytest.raises((SessionBusyError, ConfigError)):
                    competitor.resume_session(session_id)
            finally:
                await competitor.close()
        client.portal.call(confirm_actual_writer_lock)
        contexts = []
        for _ in range(3):
            preview = detail(client, identity)
            assert preview['sdk_session_id'] == session_id
            assert preview['context']['snapshot'] is True
            assert preview['context']['tokens'] > 0 and preview['context']['window'] == expected_window
            assert preview['context']['source'] in {'estimated', 'usage_calibrated'}
            contexts.append(preview['context'])
        assert contexts[0] == contexts[1] == contexts[2]
        assert event_path.read_bytes() == before
        assert (workspace / 'created.txt').read_text(encoding='utf-8') == '原生文件工具已经完成。\n'
    finally:
        client.portal.call(tui.close)
