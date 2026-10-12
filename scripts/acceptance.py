"""在两个专用工程调用真实模型，核验原生 SDK 与真实 HTTP 测试。"""
from __future__ import annotations

import argparse
import ast
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import time

import httpx


PROMPT = '''请在当前空白专用验收工程自主创建 Python 标准库 Todo HTTP JSON 后端。
只在当前目录工作，不读写任何用户配置或其他工程；不要使用 Docker 或第三方依赖。
文件必须为 app.py、tests/test_api.py、README.md。API包括GET /health、GET /todos、POST /todos、GET /todos/{id}、PATCH /todos/{id}、DELETE /todos/{id}。
POST成功返回201；空标题/错误JSON返回400；不存在返回404；PATCH验证completed必须布尔。
tests/test_api.py用unittest启动真实127.0.0.1 HTTP服务，通过urllib实际请求验证，恰好8个test_方法：健康、初始列表、创建201、读取、更新、删除、非法输入、404。
用run_command执行 python -m unittest discover -s tests -v（使用实际可用Python，yield_ms=60000，lifetime=turn），看到真实8项通过；失败就读取并修复后重测。
现有文件覆盖前先read_file；完成后说明真实结果。测试须关闭其服务器，不留下后台进程。'''


def results(state):
    return [entry for message in state.get('messages', [])
            for entry in message.get('trace', {}).get('entries', []) if entry['kind'] == 'tool_result']


def inspect_case(state, workspace):
    assert state['status'] == 'completed', state.get('result')
    paths = ('app.py', 'tests/test_api.py', 'README.md')
    assert all((workspace / path).is_file() for path in paths)
    source = (workspace / 'tests' / 'test_api.py').read_text(encoding='utf-8-sig')
    tree = ast.parse(source)
    tests = [node.name for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
             and node.name.startswith('test_')]
    assert len(tests) == 8, f'源码应有8项测试，实际{len(tests)}'
    assert any(marker in source for marker in ('urlopen', 'HTTPConnection', 'httpx.', 'requests.')), '未找到实际HTTP请求测试'
    traces = results(state)
    runs = [entry for entry in traces if entry['tool_name'] == 'run_command']
    accepted = []
    for entry in runs:
        metadata = entry.get('metadata', {})
        output = metadata.get('content', entry.get('text', ''))
        if entry.get('ok') and metadata.get('exit_code') == 0 and re.search(r'Ran\s+8\s+tests', output) and re.search(r'\bOK\b', output):
            accepted.append({'process_id': metadata.get('process_id'), 'exit_code': 0, 'output': output})
    assert accepted, '没有真实run_command退出0且Ran8tests/OK的工具结果'
    assert state.get('sdk_session_id') and (workspace / '.lancher' / 'sessions' / state['sdk_session_id']).is_dir()
    assert not any(row['status'] in {'running', 'starting'} for row in state.get('processes', [])), '验收遗留后台进程'
    return {'chat_id': state['id'], 'sdk_session_id': state['sdk_session_id'], 'workspace': str(workspace),
            'status': state['status'], 'test_names': tests, 'actual_http_test_count': 8,
            'command_results': accepted, 'tool_names': sorted({entry['tool_name'] for entry in traces}),
            'usage': state.get('usage'), 'watermark': state.get('watermark')}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:8765')
    parser.add_argument('--model', help='指定共享模型目录中的供应商/模型ID，默认当前默认模型')
    parser.add_argument('--timeout', type=float, default=600)
    parser.add_argument('--output', type=Path, default=Path(__file__).resolve().parents[1] / 'data' / 'acceptance.json')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    base = root / 'data' / 'acceptance_projects'
    base.mkdir(parents=True, exist_ok=True)
    report = {'started_at': datetime.now(timezone.utc).isoformat(), 'passed': False,
              'boundary': '真实在线模型、原生 SDK 文件与命令工具、专用工程、实际HTTP请求；没有演示Provider或Docker运行依赖。',
              'cases': [], 'overlap_seen': False}
    identities = []
    with httpx.Client(base_url=args.url.rstrip('/'), timeout=20) as client:
        def request(method, path, **kwargs):
            response = client.request(method, path, **kwargs)
            response.raise_for_status()
            return response.json()
        try:
            bootstrap = request('GET', '/api/bootstrap')
            report['sdk_commit'] = bootstrap['sdk_commit']
            model = args.model or next((row['id'] for row in bootstrap['models'] if row.get('default')), None)
            assert model, '共享模型配置没有可用默认模型'
            report['model'] = model
            for label in ('todo-a', 'todo-b'):
                workspace = base / f'{stamp}-{label}'
                workspace.mkdir()
                project = request('POST', '/api/projects', json={'path': str(workspace), 'name': f'验收 · {label}'})
                chat = request('POST', '/api/chats', json={'project_id': project['id'], 'title': f'在线验收 · {label}', 'model_ref': model})
                request('POST', f"/api/chats/{chat['id']}/actions", json={'action': 'phase', 'phase': 'execute'})
                request('POST', f"/api/chats/{chat['id']}/actions", json={'action': 'access', 'access': 'project'})
                identities.append((chat['id'], workspace))
            for identity, _workspace in identities:
                request('POST', f'/api/chats/{identity}/turns', json={'prompt': PROMPT})
            finished = set()
            deadline = time.monotonic() + args.timeout
            while time.monotonic() < deadline and len(finished) < len(identities):
                states = [(identity, workspace, request('GET', f'/api/chats/{identity}')) for identity, workspace in identities]
                if all(state['status'] in {'running', 'waiting_permission'} for _, _, state in states):
                    report['overlap_seen'] = True
                for identity, workspace, state in states:
                    if identity in finished:
                        continue
                    for permission in state.get('permissions', []):
                        # 只批准专用工程内的Python测试命令或文件范围；其他请求明确拒绝。
                        paths = permission.get('file_paths', [])
                        bounded = bool(paths) and all(Path(path).resolve().is_relative_to(workspace.resolve()) for path in paths)
                        command = permission.get('command') or ''
                        test_command = permission.get('kind') == 'command' and '-m unittest' in command and not any(
                            token in command for token in ('Remove-Item', 'Invoke-WebRequest', 'curl ', 'docker ', 'pip install'))
                        outcome = 'allow_once' if bounded or test_command else 'deny'
                        request('POST', f"/api/chats/{identity}/permissions/{permission['request_id']}", json={'outcome': outcome})
                    if state['status'] in {'completed', 'failed', 'cancelled', 'interrupted'}:
                        evidence = inspect_case(state, workspace)
                        report['cases'].append(evidence)
                        finished.add(identity)
                        print(f"通过: {workspace.name} · 8项真实HTTP测试", flush=True)
                time.sleep(0.2)
            assert len(finished) == 2, '在线验收超过等待时间'
            assert report['overlap_seen'], '未观察到两个不同工程并行运行'
            cursor = request('GET', '/api/bootstrap')['watermark']
            with client.stream('GET', '/api/events', params={'after': cursor - 2}) as response:
                response.raise_for_status()
                events = []
                for line in response.iter_lines():
                    if line.startswith('data: '):
                        events.append(json.loads(line[6:]))
                        if len(events) == 2:
                            break
            assert [row['sequence'] for row in events] == [cursor - 1, cursor]
            report['replay_sequences'] = [row['sequence'] for row in events]
            report['passed'] = True
        except Exception as error:
            report['error'] = f'{type(error).__name__}: {error}'
            raise
        finally:
            for identity, _workspace in identities:
                try:
                    state = request('GET', f'/api/chats/{identity}')
                    if state['status'] in {'running', 'queued', 'waiting_permission', 'stopping'}:
                        request('POST', f'/api/chats/{identity}/stop', json={'scope': 'session'})
                    request('POST', f'/api/chats/{identity}/actions', json={'action': 'release'})
                except Exception:
                    pass
            report['finished_at'] = datetime.now(timezone.utc).isoformat()
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'真实在线验收通过；证据写入 {args.output}', flush=True)


if __name__ == '__main__':
    main()

