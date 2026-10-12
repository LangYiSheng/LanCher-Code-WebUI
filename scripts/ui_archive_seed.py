"""只在独立 UI fixture 中准备真实 SDK 归档历史；不调用在线模型。"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import socket
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / 'tests'))

from fastapi.testclient import TestClient
from lancher_code.sessions.repository import ProjectSessionRepository
from provider_helpers import Reply, ScriptedProvider
from test_integration import action, chat, complete, detail, project, request, submit, traces
from ui_acceptance_fixture import prepare
from webui.api import create_app


def main():
    with socket.socket() as probe:
        probe.settimeout(0.3)
        if probe.connect_ex(('127.0.0.1', 8767)) == 0:
            raise RuntimeError('请先关闭独立 8767 验收服务，再准备归档样本。')
    fixture, home = prepare()
    proof_path = fixture / 'archive-proof.json'
    if proof_path.exists():
        proof = json.loads(proof_path.read_text(encoding='utf-8'))
        print(json.dumps({'existing': True, 'project_id': proof['project_id'], 'archives': proof['archives']}, ensure_ascii=False))
        return
    workspace = fixture / 'project-archive-ui'
    workspace.mkdir(exist_ok=False)
    file = workspace / 'archive-proof.md'
    file.write_text('# 独立归档验收\n\n这份工程只用于 UI 验收。\n', encoding='utf-8')
    provider = ScriptedProvider()
    prompt = '保存一份原生读取和写入工具记录供设置归档入口验收。'
    provider.plans[prompt] = [
        Reply(tools=[('read_file', {'path': 'archive-proof.md'})]),
        Reply(tools=[('write_file', {'path': 'archive-proof.md', 'content': '# 独立归档验收\n\n由 SDK 原生读写工具确认；归档后工程文件与历史保留。\n'})]),
        Reply(text='原生读写已完成，这份历史可以在设置归档列表中只读打开或恢复。'),
    ]
    archives = []
    with TestClient(create_app(root=fixture, user_home=home, provider_factory=lambda _: provider,
                              enable_mcp=False), raise_server_exceptions=False) as client:
        project_id = project(client, workspace)
        request(client, 'PATCH', f'/api/projects/{project_id}', json={'name': 'UI 归档验收项目'})
        for title, text in [('归档验收 · 原生读写记录', prompt),
                            ('归档验收 · 第二段历史', '保存第二段真实 SDK 历史，供归档搜索和筛选验收。')]:
            identity = chat(client, project_id, title)
            action(client, identity, 'phase', phase='execute')
            submit(client, identity, text)
            final = complete(client, identity)
            assert final['status'] == 'completed'
            results = traces(final)
            if text == prompt:
                assert len(results) == 2 and all(row['ok'] for row in results)
            archived = request(client, 'PATCH', f'/api/chats/{identity}', json={'archived': True})
            assert archived['archived']
            saved = detail(client, identity)
            paths = ProjectSessionRepository(workspace).paths(saved['sdk_session_id'])
            data = paths.events.read_bytes()
            info = next(row for row in ProjectSessionRepository(workspace).list_sessions().items
                        if row.session_id == saved['sdk_session_id'])
            assert info.archived and data.count(b'session.archived') == 1
            archives.append({'chat_id': identity, 'sdk_session_id': saved['sdk_session_id'], 'title': title,
                             'archived': True, 'native_archived': True, 'history_sha256': hashlib.sha256(data).hexdigest(),
                             'history_path': str(paths.events), 'message_count': len(saved['messages']),
                             'tool_results': [{'tool': row['tool_name'], 'ok': row['ok']} for row in results]})
        impact = request(client, 'GET', f'/api/projects/{project_id}/impact')
        assert impact['tasks'] == [] and impact['processes'] == []
        assert file.is_file()
        proof = {'project_id': project_id, 'workspace': str(workspace), 'fixture_root': str(fixture),
                 'user_home': str(home), 'provider': 'injected test provider; native SDK sessions and file tools',
                 'online_requests': False, 'archives': archives, 'file': str(file),
                 'file_sha256': hashlib.sha256(file.read_bytes()).hexdigest(), 'tasks': [], 'processes': []}
        proof_path.write_text(json.dumps(proof, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(proof, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
