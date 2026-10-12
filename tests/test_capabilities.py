"""计划、压缩、Skills、MCP 和删除均经过 HTTP 与固定 SDK 的真实生命周期。"""
from __future__ import annotations

import sys

from fastapi.testclient import TestClient
import yaml

from lancher_code.contracts.messages import ContentBlock, StreamEvent
from lancher_code.context.summary import SUMMARY_HEADINGS
from lancher_code.usage.models import MessageUsage

from provider_helpers import Reply, ScriptedProvider
from test_integration import action, chat, complete, detail, project, submit, traces, wait


def _request_text(outgoing):
    """SDK 把变化中的技能正文投影到 host_update，固定系统前缀保持稳定。"""
    return '\n'.join([*outgoing.system, *[block.text for item in outgoing.messages
        for block in item.blocks if block.kind == 'text']])

def _capture_provider(monkeypatch, provider):
    """保留真实请求投影，确认 Skill 正文确实进入 SDK 请求。"""
    captured = []
    original = provider.stream_chat

    async def stream(outgoing):
        captured.append(outgoing)
        async for event in original(outgoing):
            yield event

    monkeypatch.setattr(provider, 'stream_chat', stream)
    return captured


def test_plan_version_binding_and_confirmed_native_execution(client, isolated, provider):
    from pathlib import Path
    workspace = isolated[2]
    first = '# 实施计划\n- [ ] 创建 result.txt\n- [ ] 写入第一版结果\n'
    revised = '# 修订计划\n- [ ] 创建 result.txt\n- [ ] 写入确认的第二版结果\n'
    provider.plans['制定计划'] = [
        Reply(tools=[('write_plan_file', {'content': first})]),
        Reply(text='第一版待办计划已准备，请确认。'),
    ]
    provider.plans['修订计划'] = [
        Reply(tools=[('write_plan_file', {'content': revised})]),
        Reply(text='第二版待办计划已准备，请确认。'),
    ]
    identity = chat(client, project(client, workspace))
    action(client, identity, 'phase', phase='plan')
    submit(client, identity, '制定计划')
    initial = complete(client, identity)
    assert initial['status'] == 'completed' and initial['phase'] == 'plan'
    assert initial['plan']['ready'] and initial['plan']['content'] == first
    assert traces(initial, 'write_plan_file')[0]['ok']
    assert not (workspace / 'result.txt').exists()
    old_digest = initial['plan']['digest']

    submit(client, identity, '修订计划')
    planned = complete(client, identity)
    current = planned['plan']
    assert current['ready'] and current['content'] == revised
    assert current['digest'] != old_digest
    planned_path = traces(planned, 'write_plan_file')[-1]['metadata']['path']
    assert Path(planned_path).read_text(encoding='utf-8') == revised
    assert Path(planned_path).is_relative_to(workspace / '.lancher' / 'sessions')

    request_count = len(provider.requests)
    for stale in (old_digest, 'stale-digest'):
        denied = client.post(f'/api/chats/{identity}/actions',
            json={'action': 'plan_execute', 'digest': stale})
        assert denied.status_code == 409
    rejected = detail(client, identity)
    assert rejected['phase'] == 'plan' and rejected['plan']['ready']
    assert len(provider.requests) == request_count and not (workspace / 'result.txt').exists()

    confirmed_prompt = f"按我确认的以下计划开始执行。\n计划版本：{current['digest']}\n\n{revised}"
    provider.plans[confirmed_prompt] = [
        Reply(tools=[('write_file', {'path': 'result.txt', 'content': 'confirmed second revision\n'})]),
        Reply(text='确认的第二版已经执行。'),
    ]
    action(client, identity, 'plan_execute', digest=current['digest'])
    executed = complete(client, identity)
    assert executed['status'] == 'completed' and executed['phase'] == 'execute'
    assert executed['plan']['ready'] is False
    assert (workspace / 'result.txt').read_text(encoding='utf-8') == 'confirmed second revision\n'
    assert traces(executed, 'write_file')[0]['ok']
    assert provider.requests[-1]['prompt'] == confirmed_prompt
    assert client.post(f'/api/chats/{identity}/actions',
        json={'action': 'plan_execute', 'digest': current['digest']}).status_code == 409


class CompactionProvider(ScriptedProvider):
    """仅摘要响应单独注入；普通任务继续使用共享确定性 Provider。"""

    def __init__(self):
        super().__init__()
        self.compaction_requests = []
        self.chat_requests = []

    async def stream_chat(self, outgoing):
        if outgoing.purpose != 'compaction':
            self.chat_requests.append(outgoing)
            async for event in super().stream_chat(outgoing):
                yield event
            return
        self.compaction_requests.append(outgoing)
        summary = '<summary>\n' + '\n'.join(
            f'## {heading}\n已保存三轮历史资料，下一步按用户新请求继续。' for heading in SUMMARY_HEADINGS
        ) + '\n</summary>'
        yield StreamEvent(kind='text_delta', text=summary)
        yield StreamEvent(kind='message_end', response_complete=True,
            assistant_blocks=[ContentBlock.text_block(summary)],
            usage=MessageUsage(input_tokens=311, output_tokens=21, cached_input_tokens=11))


def test_compaction_preserves_records_usage_and_restored_request_context(isolated):
    from webui.api import create_app
    root, home, workspace = isolated
    provider = CompactionProvider()
    with TestClient(create_app(root=root, user_home=home, provider_factory=lambda _: provider,
                               enable_mcp=False), raise_server_exceptions=False) as client:
        identity = chat(client, project(client, workspace))
        prompts = [f'历史资料第 {index} 轮：' + '历史证据。' * 3000 for index in range(3)]
        for prompt in prompts:
            # 用量是 fixture 供应商明确上报的值；汇总校验使用同一事实源。
            provider.plans[prompt] = [Reply(text='历史资料已经登记。',
                usage=MessageUsage(input_tokens=50000, output_tokens=5, cached_input_tokens=12000))]
            submit(client, identity, prompt)
            assert complete(client, identity)['status'] == 'completed'
        before = detail(client, identity)
        original_messages = [(item['id'], item['content']) for item in before['messages']]
        assert before['usage']['session']['request_count'] == 3

        action(client, identity, 'effort', effort='high')
        action(client, identity, 'compact')
        compacted = complete(client, identity)
        assert compacted['status'] == 'completed', compacted.get('result')
        activity, = compacted['compactions'].values()
        assert activity['status'] == 'completed' and activity['trigger'] == 'manual'
        assert activity['after_tokens'] < activity['before_tokens']
        assert [(item['id'], item['content']) for item in compacted['messages']] == original_messages
        assert len(provider.compaction_requests) == 1
        outgoing = provider.compaction_requests[0]
        assert outgoing.purpose == 'compaction' and outgoing.tools == [] and not outgoing.allow_tool_calls
        assert outgoing.reasoning_effort == 'high' and outgoing.api_mode == 'chat_completions_legacy'
        assert compacted['usage']['session']['request_count'] == 4
        assert compacted['usage']['session']['input_tokens'] == 150311
        assert compacted['usage']['session']['output_tokens'] == 36
        assert compacted['usage']['session']['cached_input_tokens'] == 36011

        manager = client.app.state.manager

        async def records():
            return manager.store.requests(chat_id=identity)

        recorded = client.portal.call(records)
        summary_record, = [item for item in recorded if item['purpose'] == 'compaction']
        assert summary_record['usage']['input_tokens'] == 311
        session_id = compacted['sdk_session_id']
        action(client, identity, 'release')
        restored = detail(client, identity)
        assert restored['sdk_session_id'] == session_id
        assert restored['compactions'] == compacted['compactions']
        assert restored['usage']['session'] == compacted['usage']['session']
        assert [(item['id'], item['content']) for item in restored['messages']] == original_messages
        submit(client, identity, '压缩恢复之后继续')
        resumed = complete(client, identity)
        assert resumed['status'] == 'completed' and resumed['sdk_session_id'] == session_id
        projected = '\n'.join(block.text for item in provider.chat_requests[-1].messages for block in item.blocks
                              if block.kind == 'text')
        assert '以下内容是较早会话的压缩历史' in projected and '主要请求和意图' in projected
        assert resumed['usage']['session']['request_count'] == 5
        assert len(resumed['messages']) == len(original_messages) + 2


def _skill(root, name, body, *, description='专用验收技能'):
    directory = root / '.lancher' / 'skills' / name
    directory.mkdir(parents=True, exist_ok=True)
    (directory / 'SKILL.md').write_text(
        f'---\nname: {name}\ndescription: {description}\n---\n{body}\n', encoding='utf-8')
    return directory


def test_user_project_skills_control_real_load_and_request_projection(client, isolated, provider, monkeypatch):
    _, home, workspace = isolated
    _skill(home, 'review', '用户来源验收指南。')
    local = _skill(workspace, 'review', '项目来源验收指南。')
    (local / 'notes.txt').write_text('项目引用资料。\n第二行。\n', encoding='utf-8')
    captured = _capture_provider(monkeypatch, provider)
    identity = chat(client, project(client, workspace))

    catalogue = action(client, identity, 'skills_list')['skills']
    assert {item['id'] for item in catalogue} == {'user/review', 'project/review'}
    assert next(item for item in catalogue if item['id'] == 'user/review')['shadowed']
    assert not next(item for item in catalogue if item['id'] == 'project/review')['shadowed']
    assert '用户来源验收指南' in action(client, identity, 'skills_show', name='user/review')['text']
    assert '项目来源验收指南' in action(client, identity, 'skills_show', name='review')['text']
    action(client, identity, 'skills_disable', name='review')
    provider.plans['禁用技能读取'] = [
        Reply(tools=[('load_skill', {'skill': 'project/review'})]), Reply(text='技能禁用已经生效。')]
    submit(client, identity, '禁用技能读取')
    disabled = complete(client, identity)
    failure, = traces(disabled, 'load_skill')
    assert not failure['ok'] and failure['metadata']['error_code'] == 'skill_disabled'

    action(client, identity, 'skills_enable', name='project/review')
    provider.plans['读取两个来源技能'] = [
        Reply(tools=[('load_skill', {'skill': 'project/review'}),
                     ('load_skill', {'skill': 'user/review'})]),
        Reply(tools=[('read_skill_resource', {'skill': 'project/review', 'relative_path': 'notes.txt'})]),
        Reply(text='两个来源的指南与项目引用已经读入。'),
    ]
    submit(client, identity, '读取两个来源技能')
    loaded = complete(client, identity)
    loaded_results = [item for item in traces(loaded, 'load_skill') if item['ok']]
    assert {item['metadata']['skill_id'] for item in loaded_results} == {'user/review', 'project/review'}
    assert all('body' not in item['metadata'] for item in loaded_results)
    resource, = traces(loaded, 'read_skill_resource')
    assert resource['ok'] and '项目引用资料' in resource['metadata']['content']
    blocks = _request_text(captured[-1])
    assert '<active_skill id="project/review">' in blocks and '项目来源验收指南' in blocks
    assert '<active_skill id="user/review">' in blocks and '用户来源验收指南' in blocks
    assert all(item['loaded'] and item['enabled'] for item in loaded['capabilities']['skills'])

    action(client, identity, 'skills_unload', name='project/review')
    _skill(workspace, 'review', '项目来源刷新后的验收指南。')
    _skill(workspace, 'extra', '新增技能正文。')
    refreshed = action(client, identity, 'skills_reload')
    assert '3 个技能' in refreshed['text']
    assert '项目来源刷新后的验收指南' in action(client, identity, 'skills_show', name='review')['text']
    provider.plans['刷新后读取技能'] = [
        Reply(tools=[('load_skill', {'skill': 'project/review'})]), Reply(text='已使用刷新后的指南。')]
    submit(client, identity, '刷新后读取技能')
    assert complete(client, identity)['status'] == 'completed'
    assert '项目来源刷新后的验收指南' in _request_text(captured[-1])
    action(client, identity, 'release')
    restored = action(client, identity, 'skills_list')['skills']
    assert next(item for item in restored if item['id'] == 'project/review')['loaded']


MCP_SERVER = """from mcp.server.fastmcp import FastMCP
import os
server = FastMCP('WebUI dedicated acceptance')

@server.tool(annotations={'readOnlyHint': True})
def echo(value: str) -> str:
    # 通过真实 stdio 返回作用域标记。
    return os.environ['FIXTURE_SCOPE'] + ':' + value

if __name__ == '__main__':
    server.run(transport='stdio')
"""


def _mcp_config(path, server_name, executable, script, scope):
    path.parent.mkdir(parents=True, exist_ok=True)
    config = {'mcp_servers': {server_name: {
        'type': 'stdio', 'command': executable, 'args': ['-B', str(script)],
        'env': {'FIXTURE_SCOPE': scope, 'PYTHONDONTWRITEBYTECODE': '1'},
        'startup_timeout_seconds': 15, 'tool_timeout_seconds': 10, 'close_timeout_seconds': 5,
    }}}
    path.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding='utf-8')


def test_dedicated_stdio_mcp_user_project_refresh_reload_and_tool_call(isolated, provider):
    from webui.api import create_app
    root, home, workspace = isolated
    script = workspace.parent / 'acceptance_mcp_server.py'
    script.write_text(MCP_SERVER, encoding='utf-8')
    _mcp_config(home / '.lancher' / 'mcp.yaml', 'userfixture', sys.executable, script, 'user')
    project_config = workspace / '.lancher' / 'mcp.yaml'
    _mcp_config(project_config, 'projectfixture', sys.executable, script, 'project')
    with TestClient(create_app(root=root, user_home=home, provider_factory=lambda _: provider,
                               enable_mcp=True), raise_server_exceptions=False) as client:
        identity = chat(client, project(client, workspace))
        action(client, identity, 'mcp_status')
        ready = wait(client, identity, lambda value: len(value['capabilities']['mcp']) == 2
            and all(item['state'] == 'ready' for item in value['capabilities']['mcp']), timeout=30)
        assert {item['name'] for item in ready['capabilities']['mcp']} == {'userfixture', 'projectfixture'}
        assert all(item['registered_tools'] == 1 for item in ready['capabilities']['mcp'])
        assert '已刷新' in action(client, identity, 'mcp_refresh', name='projectfixture')['text']

        provider.plans['调用两个来源的 MCP'] = [
            Reply(tools=[('tool_search', {'query': 'echo'})]),
            Reply(tools=[('mcp__userfixture__echo', {'value': 'scope-call'}),
                         ('mcp__projectfixture__echo', {'value': 'scope-call'})]),
            Reply(text='两个 stdio 工具调用完成。'),
        ]
        submit(client, identity, '调用两个来源的 MCP')
        initial = complete(client, identity, timeout=60)
        assert initial['status'] == 'completed'
        results = {item['tool_name']: item for item in traces(initial) if item['tool_name'].startswith('mcp__')}
        assert set(results) == {'mcp__userfixture__echo', 'mcp__projectfixture__echo'}
        assert all(item['ok'] for item in results.values())
        assert 'user:scope-call' in results['mcp__userfixture__echo']['metadata']['content']
        assert 'project:scope-call' in results['mcp__projectfixture__echo']['metadata']['content']

        # 只修改本测试的项目层；重新装配须保留会话历史并采用新连接环境。
        _mcp_config(project_config, 'projectfixture', sys.executable, script, 'project-v2')
        reloaded = action(client, identity, 'mcp_reload')
        assert reloaded['text']
        assert detail(client, identity)['sdk_session_id'] == initial['sdk_session_id']
        assert all(item['state'] == 'ready' for item in detail(client, identity)['capabilities']['mcp'])
        provider.plans['重载后调用 MCP'] = [
            Reply(tools=[('tool_search', {'query': 'select:mcp__projectfixture__echo'})]),
            Reply(tools=[('mcp__projectfixture__echo', {'value': 'new-config'})]),
            Reply(text='新 MCP 配置已用于真实调用。'),
        ]
        submit(client, identity, '重载后调用 MCP')
        final = complete(client, identity, timeout=60)
        remote, = [item for item in traces(final, 'mcp__projectfixture__echo')
                   if 'project-v2:new-config' in item['metadata'].get('content', '')]
        assert remote['ok']
        assert len([item for item in final['messages'] if item['role'] == 'user']) == 2


def test_native_delete_directory_requires_recursive_and_recreates_from_backup(client, isolated, provider):
    workspace = isolated[2]
    target = workspace / 'disposable'
    (target / 'nested').mkdir(parents=True)
    backup = '专用目录的可恢复原文。\n'
    (target / 'restore.txt').write_text(backup, encoding='utf-8')
    (target / 'nested' / 'second.txt').write_text('第二份资料。\n', encoding='utf-8')
    sentinel = workspace / 'keep.txt'
    sentinel.write_text('保留工程文件。\n', encoding='utf-8')
    identity = chat(client, project(client, workspace))

    provider.plans['缺少递归删除标志'] = [
        Reply(tools=[('delete_file', {'path': 'disposable'})]), Reply(text='缺少显式递归标志。')]
    submit(client, identity, '缺少递归删除标志')
    refused = complete(client, identity)
    refused_result, = traces(refused, 'delete_file')
    assert not refused_result['ok'] and refused_result['metadata']['error_code'] == 'recursive_required'
    assert (target / 'restore.txt').read_text(encoding='utf-8') == backup

    provider.plans['删除专用文件'] = [
        Reply(tools=[('read_file', {'path': 'disposable/restore.txt'})]),
        Reply(tools=[('delete_file', {'path': 'disposable/restore.txt'})]),
        Reply(text='专用文件已经删除。'),
    ]
    submit(client, identity, '删除专用文件')
    deleted = complete(client, identity)
    result = traces(deleted, 'delete_file')[-1]
    assert result['ok'] and result['metadata']['deleted_count'] == 1
    assert not (target / 'restore.txt').exists()
    provider.plans['按备份恢复专用文件'] = [
        Reply(tools=[('write_file', {'path': 'disposable/restore.txt', 'content': backup})]),
        Reply(text='已按备份重新写入文件。'),
    ]
    submit(client, identity, '按备份恢复专用文件')
    restored = complete(client, identity)
    assert traces(restored, 'write_file')[-1]['ok']
    assert (target / 'restore.txt').read_text(encoding='utf-8') == backup

    provider.plans['递归删除专用目录'] = [
        Reply(tools=[('delete_file', {'path': 'disposable', 'recursive': True})]),
        Reply(text='专用目录已经清理。'),
    ]
    submit(client, identity, '递归删除专用目录')
    cleaned = complete(client, identity)
    final = traces(cleaned, 'delete_file')[-1]
    assert final['ok'] and final['metadata']['recursive'] is True
    assert final['metadata']['deleted_count'] == 4 and not target.exists()
    assert sentinel.read_text(encoding='utf-8') == '保留工程文件。\n'
    assert (workspace / '.lancher' / 'sessions' / cleaned['sdk_session_id']).is_dir()