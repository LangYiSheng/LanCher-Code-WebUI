"""对话文件变更按首次原生编辑前基线分类，工程浏览保持完整。"""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess

import pytest

from provider_helpers import Reply
from test_integration import chat, complete, project, request, submit, traces


def file_rows(client, project_id, identity=None, *, changes=False):
    params = {}
    if identity:
        params['chat_id'] = identity
    if changes:
        params['scope'] = 'changes'
    return request(client, 'GET', f'/api/projects/{project_id}/files', params=params)


def assert_no_changes(client, project_id, identity):
    result = file_rows(client, project_id, identity, changes=True)
    assert result['scope'] == 'changes'
    assert result['change_tracking'] == 'native_file_tools'
    assert result['files'] == [] and result['change_count'] == 0
    assert result['change_summary'] == {'added': 0, 'modified': 0, 'deleted': 0}


def test_native_edit_restored_to_original_is_unchanged(client, isolated, provider):
    workspace = isolated[2]
    original = 'alpha\nbeta\n'
    (workspace / 'module.txt').write_text(original, encoding='utf-8')
    project_id = project(client, workspace)
    identity = chat(client, project_id)
    provider.plans['先修改原文'] = [
        Reply(tools=[('read_file', {'path': 'module.txt'})]),
        Reply(tools=[('edit_file', {'path': 'module.txt', 'old_text': 'beta', 'new_text': 'gamma'})]),
        Reply(text='原生修改完成。'),
    ]
    submit(client, identity, '先修改原文')
    first = complete(client, identity)
    assert first['status'] == 'completed' and traces(first, 'edit_file')[-1]['ok']
    modified = file_rows(client, project_id, identity, changes=True)
    assert modified['change_count'] == 1 and modified['files'][0]['status'] == 'modified'

    provider.plans['恢复原文'] = [
        Reply(tools=[('read_file', {'path': 'module.txt'})]),
        Reply(tools=[('edit_file', {'path': 'module.txt', 'old_text': 'gamma', 'new_text': 'beta'})]),
        Reply(text='已恢复首次修改前原文。'),
    ]
    submit(client, identity, '恢复原文')
    final = complete(client, identity)
    assert final['status'] == 'completed' and traces(final, 'edit_file')[-1]['ok']
    assert (workspace / 'module.txt').read_text(encoding='utf-8') == original
    preview = request(client, 'GET', f'/api/chats/{identity}/file', params={'path': 'module.txt'})
    assert preview['diff'] == '' and preview['change_status'] == 'unchanged'
    assert_no_changes(client, project_id, identity)
    current = file_rows(client, project_id, identity)
    assert {row['path']: row['status'] for row in current['files']}['module.txt'] == 'unchanged'


def test_failed_native_edit_does_not_create_a_change(client, isolated, provider):
    workspace = isolated[2]
    original = '内容没有被修改。\n'
    (workspace / 'kept.txt').write_text(original, encoding='utf-8')
    project_id = project(client, workspace)
    identity = chat(client, project_id)
    provider.plans['匹配失败的编辑'] = [
        Reply(tools=[('read_file', {'path': 'kept.txt'})]),
        Reply(tools=[('edit_file', {'path': 'kept.txt', 'old_text': '这个文本不存在', 'new_text': 'replacement'})]),
        Reply(text='匹配失败，文件保留。'),
    ]
    submit(client, identity, '匹配失败的编辑')
    final = complete(client, identity)
    assert final['status'] == 'completed' and not traces(final, 'edit_file')[-1]['ok']
    assert (workspace / 'kept.txt').read_text(encoding='utf-8') == original
    assert_no_changes(client, project_id, identity)
    preview = request(client, 'GET', f'/api/chats/{identity}/file', params={'path': 'kept.txt'})
    assert preview['change_status'] == 'unchanged' and preview['diff'] == ''


def test_recursive_native_delete_tracks_descendants_but_not_project_browser(client, isolated, provider):
    workspace = isolated[2]
    (workspace / 'disposable' / 'nested').mkdir(parents=True)
    (workspace / 'disposable' / 'first.txt').write_text('first original\n', encoding='utf-8')
    (workspace / 'disposable' / 'nested' / 'second.txt').write_text('second original\n', encoding='utf-8')
    (workspace / 'keep.txt').write_text('unrelated\n', encoding='utf-8')
    project_id = project(client, workspace)
    identity = chat(client, project_id)
    provider.plans['删除临时目录'] = [
        Reply(tools=[('delete_file', {'path': 'disposable', 'recursive': True})]),
        Reply(text='临时目录已删除。'),
    ]
    submit(client, identity, '删除临时目录')
    final = complete(client, identity)
    assert final['status'] == 'completed' and traces(final, 'delete_file')[-1]['ok']
    result = file_rows(client, project_id, identity, changes=True)
    assert result['change_count'] == 2
    assert result['change_summary'] == {'added': 0, 'modified': 0, 'deleted': 2}
    assert {row['path']: row['status'] for row in result['files']} == {
        'disposable/first.txt': 'deleted', 'disposable/nested/second.txt': 'deleted'}
    all_files = file_rows(client, project_id, identity)
    assert {row['path'] for row in all_files['files']} == {'keep.txt'}
    preview = request(client, 'GET', f'/api/chats/{identity}/file', params={'path': 'disposable/nested/second.txt'})
    assert preview['change_status'] == 'deleted' and preview['content'] == ''
    assert '-second original' in preview['diff']


def test_empty_new_file_then_delete_has_no_net_change(client, isolated, provider):
    workspace = isolated[2]
    project_id = project(client, workspace)
    identity = chat(client, project_id)
    provider.plans['新增空文件'] = [
        Reply(tools=[('write_file', {'path': 'ephemeral.txt', 'content': ''})]),
        Reply(text='新增空文件。'),
    ]
    submit(client, identity, '新增空文件')
    first = complete(client, identity)
    assert first['status'] == 'completed' and traces(first, 'write_file')[-1]['ok']
    changed = file_rows(client, project_id, identity, changes=True)
    assert changed['change_count'] == 1
    assert changed['files'][0]['path'] == 'ephemeral.txt' and changed['files'][0]['status'] == 'added'
    provider.plans['删掉新增空文件'] = [
        Reply(tools=[('read_file', {'path': 'ephemeral.txt'})]),
        Reply(tools=[('delete_file', {'path': 'ephemeral.txt'})]),
        Reply(text='恢复不存在的初始状态。'),
    ]
    submit(client, identity, '删掉新增空文件')
    final = complete(client, identity)
    assert final['status'] == 'completed' and traces(final, 'delete_file')[-1]['ok']
    assert not (workspace / 'ephemeral.txt').exists()
    assert_no_changes(client, project_id, identity)
    assert file_rows(client, project_id, identity)['files'] == []


def test_unedited_chat_does_not_borrow_external_git_diff(client, isolated, provider):
    git = shutil.which('git')
    if not git:
        pytest.skip('本机未安装 Git，不能构造外部未提交差异。')
    workspace = isolated[2]
    target = workspace / 'outside.txt'
    target.write_text('committed original\n', encoding='utf-8')
    env = os.environ.copy()
    for key in ('GIT_DIR', 'GIT_WORK_TREE', 'GIT_INDEX_FILE'):
        env.pop(key, None)
    env['GIT_CONFIG_GLOBAL'] = os.devnull
    env['GIT_CONFIG_NOSYSTEM'] = '1'
    def local_git(*arguments):
        subprocess.run([git, '-C', str(workspace), *arguments], env=env, check=True,
            capture_output=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    local_git('init')
    local_git('add', '--', 'outside.txt')
    local_git('-c', 'user.name=UI fixture', '-c', 'user.email=ui-fixture@example.invalid', 'commit', '-m', 'fixture baseline')
    target.write_text('changed outside this chat\n', encoding='utf-8')
    project_id = project(client, workspace)
    identity = chat(client, project_id)
    provider.plans['只读取外部修改文件'] = [
        Reply(tools=[('read_file', {'path': 'outside.txt'})]), Reply(text='读取完成。')]
    submit(client, identity, '只读取外部修改文件')
    final = complete(client, identity)
    assert final['status'] == 'completed' and traces(final, 'read_file')[-1]['ok']
    preview = request(client, 'GET', f'/api/chats/{identity}/file', params={'path': 'outside.txt'})
    assert preview['content'] == 'changed outside this chat\n'
    assert preview['diff'] == '' and preview['diff_source'] == 'none'
    assert preview['change_status'] == 'unchanged'
    assert_no_changes(client, project_id, identity)
    source = request(client, 'GET', f'/api/projects/{project_id}/file', params={'path': 'outside.txt'})
    assert source['content'] == 'changed outside this chat\n' and not source.get('diff')


def test_changes_are_scoped_to_chat_and_require_chat_id(client, isolated, provider):
    workspace = isolated[2]
    (workspace / 'shared.txt').write_text('old\n', encoding='utf-8')
    project_id = project(client, workspace)
    first = chat(client, project_id)
    second = chat(client, project_id)
    provider.plans['第一个聊天编辑'] = [
        Reply(tools=[('read_file', {'path': 'shared.txt'})]),
        Reply(tools=[('edit_file', {'path': 'shared.txt', 'old_text': 'old', 'new_text': 'new'})]),
        Reply(text='第一次修改完成。'),
    ]
    submit(client, first, '第一个聊天编辑')
    assert complete(client, first)['status'] == 'completed'
    assert file_rows(client, project_id, first, changes=True)['change_count'] == 1
    assert_no_changes(client, project_id, second)
    preview = request(client, 'GET', f'/api/chats/{second}/file', params={'path': 'shared.txt'})
    assert preview['content'] == 'new\n' and preview['diff'] == '' and preview['diff_source'] == 'none'
    missing = client.get(f'/api/projects/{project_id}/files', params={'scope': 'changes'})
    assert missing.status_code in {400, 422}
    other_workspace = workspace.parent / 'different-project'
    other_workspace.mkdir()
    other_project = project(client, other_workspace)
    wrong = client.get(f'/api/projects/{other_project}/files', params={'scope': 'changes', 'chat_id': first})
    assert wrong.status_code == 403


def test_delete_existing_empty_file_is_deleted_not_absent_baseline(client, isolated, provider):
    workspace = isolated[2]
    (workspace / 'existing-empty.txt').write_text('', encoding='utf-8')
    project_id = project(client, workspace)
    identity = chat(client, project_id)
    provider.plans['删除原有空文件'] = [
        Reply(tools=[('read_file', {'path': 'existing-empty.txt'})]),
        Reply(tools=[('delete_file', {'path': 'existing-empty.txt'})]),
        Reply(text='原有空文件已删除。'),
    ]
    submit(client, identity, '删除原有空文件')
    final = complete(client, identity)
    assert final['status'] == 'completed' and traces(final, 'delete_file')[-1]['ok']
    changed = file_rows(client, project_id, identity, changes=True)
    assert changed['change_count'] == 1 and changed['change_summary']['deleted'] == 1
    assert changed['files'][0]['status'] == 'deleted'
    preview = request(client, 'GET', f'/api/chats/{identity}/file', params={'path': 'existing-empty.txt'})
    assert preview['deleted'] is True and preview['change_status'] == 'deleted'
    assert preview['content'] == '' and preview['diff_source'] == 'baseline'
    assert file_rows(client, project_id, identity)['files'] == []


def test_native_edit_without_final_newline_has_standard_diff_markers(client, isolated, provider):
    workspace = isolated[2]
    (workspace / 'no-newline.txt').write_text('old', encoding='utf-8')
    project_id = project(client, workspace)
    identity = chat(client, project_id)
    provider.plans['修改无末尾换行文件'] = [
        Reply(tools=[('read_file', {'path': 'no-newline.txt'})]),
        Reply(tools=[('edit_file', {'path': 'no-newline.txt', 'old_text': 'old', 'new_text': 'new'})]),
        Reply(text='保留无末尾换行形态完成编辑。'),
    ]
    submit(client, identity, '修改无末尾换行文件')
    final = complete(client, identity)
    assert final['status'] == 'completed' and traces(final, 'edit_file')[-1]['ok']
    assert (workspace / 'no-newline.txt').read_bytes() == b'new'
    preview = request(client, 'GET', f'/api/chats/{identity}/file', params={'path': 'no-newline.txt'})
    assert preview['change_status'] == 'modified'
    assert '-old\n' in preview['diff'] and '+new\n' in preview['diff']
    assert preview['diff'].count('\\ No newline at end of file') == 2
    assert '-old+new' not in preview['diff']
