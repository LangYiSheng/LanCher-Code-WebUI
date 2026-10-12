"""使用测试 Provider 驱动真实 SDK 工具，为独立 UI fixture 种入真实变更。"""
from __future__ import annotations

import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / 'tests'))

from fastapi.testclient import TestClient
from provider_helpers import Reply, ScriptedProvider
from test_integration import action, chat, complete, project, request, submit, traces
from ui_acceptance_fixture import prepare
from webui.api import create_app


def main():
    fixture_root, home = prepare(sync_dist=True)
    proof_path = fixture_root / 'editor-proof.json'
    if proof_path.exists():
        proof = json.loads(proof_path.read_text(encoding='utf-8'))
        print(json.dumps({'existing': True, 'project_id': proof['project_id'], 'chat_id': proof['chat_id'],
                         'workspace': proof['workspace']}, ensure_ascii=False))
        return
    workspace = fixture_root / 'project-c-ui'
    workspace.mkdir(exist_ok=False)
    (workspace / 'old_file.py').write_text("def greeting():\n    return 'before'\n", encoding='utf-8')
    (workspace / 'deleted_file.txt').write_text('这是一份将由原生删除工具移除的 fixture 原文。\n', encoding='utf-8')
    (workspace / 'unchanged.md').write_text('# 未修改文件\n\n工程文件视图应保留这一项。\n', encoding='utf-8')
    prompt = '在独立 UI 工程运行原生编辑、新增和删除工具。'
    provider = ScriptedProvider()
    provider.plans[prompt] = [
        Reply(tools=[('read_file', {'path': 'old_file.py'})]),
        Reply(tools=[('edit_file', {'path': 'old_file.py', 'old_text': "'before'", 'new_text': "'after'"})]),
        Reply(tools=[('read_file', {'path': 'deleted_file.txt'})]),
        Reply(tools=[('delete_file', {'path': 'deleted_file.txt'})]),
        Reply(tools=[('write_file', {'path': 'notes/added.md', 'content': '# 新增文件\n\n由 SDK 原生写入工具创建。\n'})]),
        Reply(text='独立验收样本已完成：修改 old_file.py、删除 deleted_file.txt、新增 notes/added.md。未修改的工程文件保留在文件视图。'),
    ]
    with TestClient(create_app(root=fixture_root, user_home=home,
        provider_factory=lambda _config: provider, enable_mcp=False), raise_server_exceptions=False) as client:
        project_id = project(client, workspace)
        request(client, 'PATCH', f'/api/projects/{project_id}', json={'name': 'UI 检查器正例'})
        identity = chat(client, project_id, 'SDK 编辑 / 新增 / 删除样本')
        action(client, identity, 'phase', phase='execute')
        action(client, identity, 'access', access='project')
        submit(client, identity, prompt)
        final = complete(client, identity)
        assert final['status'] == 'completed'
        results = traces(final)
        assert len(results) == 5 and all(entry['ok'] for entry in results)
        changed = request(client, 'GET', f'/api/projects/{project_id}/files', params={'scope': 'changes', 'chat_id': identity})
        statuses = {entry['path']: entry['status'] for entry in changed['files']}
        assert statuses == {'old_file.py': 'modified', 'deleted_file.txt': 'deleted', 'notes/added.md': 'added'}
        assert changed['change_summary'] == {'added': 1, 'modified': 1, 'deleted': 1}
        assert (workspace / 'old_file.py').read_text(encoding='utf-8') == "def greeting():\n    return 'after'\n"
        assert not (workspace / 'deleted_file.txt').exists()
        source_files = request(client, 'GET', f'/api/projects/{project_id}/files', params={'chat_id': identity})
        assert {entry['path'] for entry in source_files['files']} == {'old_file.py', 'notes/added.md', 'unchanged.md'}
        previews = {}
        for path in statuses:
            previews[path] = request(client, 'GET', f'/api/chats/{identity}/file', params={'path': path})
            assert previews[path]['change_status'] == statuses[path]
            assert previews[path]['diff_source'] == 'baseline'
        assert "-'before'" not in previews['old_file.py']['diff']  # 实际差异包含缩进和 return。
        assert "-    return 'before'" in previews['old_file.py']['diff']
        assert "+    return 'after'" in previews['old_file.py']['diff']
        action(client, identity, 'release')
        saved = request(client, 'GET', f'/api/chats/{identity}')
        proof = {'project_id': project_id, 'chat_id': identity, 'sdk_session_id': saved['sdk_session_id'],
            'workspace': str(workspace), 'fixture_root': str(fixture_root), 'user_home': str(home),
            'provider': 'injected ScriptedProvider only for this seed; no online requests',
            'tools': 'real SDK native read_file/edit_file/delete_file/write_file',
            'status': saved['status'], 'change_count': changed['change_count'],
            'change_summary': changed['change_summary'], 'change_statuses': statuses,
            'actual_tool_results': [{'tool': item['tool_name'], 'ok': item['ok']} for item in results],
            'native_session_path': str(workspace / '.lancher' / 'sessions' / saved['sdk_session_id']),
            'context': saved['context'], 'processes': saved['processes'],
        }
        assert proof['context']['tokens'] > 0 and proof['processes'] == []
        (fixture_root / 'editor-detail.json').write_text(json.dumps(saved, ensure_ascii=False, indent=2), encoding='utf-8')
        (fixture_root / 'editor-previews.json').write_text(json.dumps(previews, ensure_ascii=False, indent=2), encoding='utf-8')
        proof_path.write_text(json.dumps(proof, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(proof, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
