"""连接真实服务验收 SDK → 文件工具 → Docker → HTTP 测试完整链路。"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import time

import httpx

TERMINAL = {'completed', 'cancelled', 'failed'}


class Acceptance:
    def __init__(self, base_url, timeout):
        self.client = httpx.Client(base_url=base_url.rstrip('/'), timeout=15)
        self.timeout = timeout
        self.cases = []
        self.session_ids = []

    def request(self, method, path, **kwargs):
        response = self.client.request(method, path, **kwargs)
        response.raise_for_status()
        return response.json()

    def create(self, title, mode='demo', model=None):
        payload = {'title': title, 'mode': mode}
        if model:
            payload['model'] = model
        state = self.request('POST', '/api/sessions', json=payload)
        self.session_ids.append(state['id'])
        return state['id']

    def detail(self, identity):
        return self.request('GET', f'/api/sessions/{identity}')

    def submit(self, identity, prompt):
        return self.request('POST', f'/api/sessions/{identity}/turns', json={'prompt': prompt})

    def wait(self, identity, predicate):
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            state = self.detail(identity)
            if predicate(state):
                return state
            time.sleep(0.1)
        raise AssertionError(f"会话等待超时: {identity}, status={state['status']}")

    def complete(self, identity, approve_tests=True):
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            state = self.detail(identity)
            for request in state['pending_permissions']:
                # 自动验收只批准受限 run_tests，其余权限请求一律拒绝。
                serialized = json.dumps(request, ensure_ascii=False)
                outcome = 'allow' if approve_tests and 'run_tests' in serialized else 'deny'
                self.request('POST', f"/api/sessions/{identity}/permissions/{request['request_id']}",
                             json={'outcome': outcome})
            if state['status'] in TERMINAL:
                assert state['status'] == 'completed', state.get('result')
                return state
            time.sleep(0.1)
        raise AssertionError(f"任务未结束: {identity}, status={state['status']}")

    @staticmethod
    def results(state, name='run_tests'):
        return [event['tool_result'] for event in state['events']
                if event['kind'] == 'tool_result_received' and event['tool_result']['tool_name'] == name]

    def record(self, name, state, **evidence):
        sequences = [event['sequence'] for event in state['events']]
        assert sequences == list(range(1, len(sequences) + 1))
        assert state['sdk_session_id']
        result = {'name': name, 'passed': True, 'session_id': state['id'],
                  'sdk_session_id': state['sdk_session_id'], 'event_count': len(state['events']),
                  'final_sequence': sequences[-1], 'status': state['status'], **evidence}
        self.cases.append(result)
        print(f"通过: {name} · {len(state['events'])} 个持久化事件", flush=True)

    def repair(self):
        identity = self.create('验收 · 故意失败并修复 Todo 后端')
        self.submit(identity, '故意失败然后修复后端，运行真实 HTTP 测试')
        state = self.complete(identity)
        results = self.results(state)
        assert len(results) == 2, f'预期失败和修复两次测试，实际 {len(results)}'
        payloads = [json.loads(result['content']) for result in results]
        first, second = payloads
        assert first['error_code'] == 'tests_failed' and first['exit_code'] != 0
        assert 'FAILED' in first['output'] and '200 != 201' in first['output']
        assert second['ok'] is True and second['exit_code'] == 0
        assert 'Ran 4 tests' in second['output'] and 'OK' in second['output']
        assert all(payload['isolation'] == 'docker' for payload in payloads)
        paths = {file['path'] for file in state['files']}
        assert {'app.py', 'tests/test_api.py', 'README.md'} <= paths
        preview = self.request('GET', f'/api/sessions/{identity}/file', params={'path': 'app.py'})
        assert 'return self.reply(201, item)' in preview['content']
        assert '+++ b/app.py' in preview['diff']
        kinds = {event['kind'] for event in state['events']}
        assert {'assistant_text_delta', 'permission_request_created', 'tool_result_received',
                'turn_completed', 'lab_files_changed', 'lab_result'} <= kinds
        self.record('真实 SDK 生成后端、Docker 测试失败、读取修复、再次通过', state,
                    files=sorted(paths), docker_results=payloads, trace_tools=[
                        event['tool_call']['tool_name'] for event in state['events']
                        if event['kind'] == 'tool_call_started'])
        return state

    def deny(self):
        identity = self.create('验收 · 审批拒绝')
        self.submit(identity, '审批拒绝实验')
        waiting = self.wait(identity, lambda state: state['status'] == 'waiting_permission')
        assert waiting['pending_permissions']
        state = self.complete(identity, approve_tests=False)
        results = self.results(state)
        assert len(results) == 1 and results[0]['error_code'] == 'permission_user_denied'
        assert not state['files'] and not state['pending_permissions']
        self.record('审批拒绝保留真实错误且未执行 Docker', state,
                    error_code=results[0]['error_code'])

    def stop_and_resume(self):
        identity = self.create('验收 · 停止、保留队列、恢复')
        self.submit(identity, '慢速停止实验')
        self.wait(identity, lambda state: any(event['kind'] == 'assistant_text_delta' for event in state['events']))
        self.request('POST', f'/api/sessions/{identity}/queue', json={'prompt': '审批队列恢复'})
        self.request('POST', f'/api/sessions/{identity}/stop')
        stopped = self.detail(identity)
        assert stopped['status'] == 'cancelled' and stopped['queue_paused']
        assert len(stopped['queue']) == 1
        assert [message['content'] for message in stopped['messages'] if message['role'] == 'user'] == ['慢速停止实验']
        assert any(event['kind'] == 'turn_cancelled' for event in stopped['events'])
        stop_sequence = stopped['events'][-1]['sequence']
        self.request('POST', f'/api/sessions/{identity}/resume')
        state = self.complete(identity, approve_tests=False)
        assert state['queue'] == []
        assert [message['content'] for message in state['messages'] if message['role'] == 'user'] == ['慢速停止实验', '审批队列恢复']
        self.record('运行中停止保留后续输入，显式恢复执行队列', state,
                    stopped_status='cancelled', stop_sequence=stop_sequence, resumed_queue_empty=True)

    def replay(self, state):
        cursor = max(0, state['events'][-1]['sequence'] - 3)
        received = []
        with self.client.stream('GET', f"/api/sessions/{state['id']}/events",
                                params={'after': 0}, headers={'Last-Event-ID': str(cursor)}) as response:
            response.raise_for_status()
            assert 'text/event-stream' in response.headers['content-type']
            for line in response.iter_lines():
                if line.startswith('data: '):
                    event = json.loads(line[6:])
                    received.append(event)
                    if len(received) == 3:
                        break
        assert [event['sequence'] for event in received] == [cursor + 1, cursor + 2, cursor + 3]
        self.record('SSE 断线后按 Last-Event-ID 连续补回事件', state,
                    replay_cursor=cursor, replay_sequences=[event['sequence'] for event in received])

    def security(self, state):
        checks = {}
        for path in ('../outside.txt', 'C:/Windows/win.ini', '.lancher/session.json', 'app.py:stream'):
            response = self.client.get(f"/api/sessions/{state['id']}/file", params={'path': path})
            assert response.status_code == 403
            checks[path] = response.status_code
        for headers in ({'Origin': 'https://attacker.example'}, {'Host': 'attacker.example'},
                        {'Sec-Fetch-Site': 'cross-site'}):
            response = self.client.get('/api/status', headers=headers)
            assert response.status_code == 403
        self.record('文件越界、隐藏元数据、ADS 与跨站访问被拒绝', state,
                    rejected_paths=checks, cross_site_status=403)

    def live(self, model):
        identity = self.create('验收 · 在线模型自主生成后端', 'live', model)
        self.submit(identity,
            '请在当前空白实验目录创建 Python 标准库 Todo HTTP JSON API：app.py、tests/test_api.py、README.md。'
            '接口至少 GET /health、GET /todos、POST /todos、GET/PATCH/DELETE /todos/{id}；创建返回201、'
            '非法title返回400、不存在返回404。tests/test_api.py 使用unittest和真实HTTP请求验证CRUD、'
            '状态码与非法输入。测试必须通过run_tests工具运行，它会在Docker内执行固定unittest发现命令。'
            '请自主检查并修复到测试通过，再说明实际验证结果。现有文件改写前先read_file；不要访问工作区外。')
        state = self.complete(identity)
        results = self.results(state)
        assert results and any(not result['is_error'] and json.loads(result['content']).get('ok') for result in results)
        assert {'app.py', 'tests/test_api.py', 'README.md'} <= {file['path'] for file in state['files']}
        self.record('在线模型自主编写并通过真实 Docker HTTP 测试', state,
                    model=model, docker_results=[json.loads(result['content']) for result in results])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:8765')
    parser.add_argument('--timeout', type=float, default=120)
    parser.add_argument('--output', type=Path, default=Path(__file__).resolve().parents[1] / 'data' / 'acceptance.json')
    parser.add_argument('--live', action='store_true', help='追加在线模型验收，产生真实模型用量')
    args = parser.parse_args()
    acceptance = Acceptance(args.url, args.timeout)
    report = {'started_at': datetime.now(timezone.utc).isoformat(), 'base_url': args.url,
              'boundary': '默认场景使用确定性演示 Provider、真实 LanCher SDK、真实 Docker 和真实 HTTP 测试；不伪造结果。',
              'passed': False}
    try:
        status = acceptance.request('GET', '/api/status')
        report['sdk_commit'], report['sdk_version'] = status['sdk_commit'], status['sdk_version']
        assert status['docker_available'], '真实 Docker 和 python:3.14-slim 镜像未就绪，不能通过完整验收。'
        state = acceptance.repair()
        acceptance.deny()
        acceptance.stop_and_resume()
        acceptance.replay(state)
        acceptance.security(state)
        if args.live:
            assert status['live_available'], '在线模型未配置。'
            acceptance.live(status['default_live_model'])
        report['passed'] = True
    except Exception as error:
        report['error'] = f'{type(error).__name__}: {error}'
        raise
    finally:
        report['finished_at'] = datetime.now(timezone.utc).isoformat()
        report['cases'] = acceptance.cases
        report['session_ids'] = acceptance.session_ids
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        # 失败也停止本脚本创建的活动会话，避免残留等待审批的任务。
        for identity in acceptance.session_ids:
            try:
                if acceptance.detail(identity)['status'] not in TERMINAL:
                    acceptance.request('POST', f'/api/sessions/{identity}/stop')
            except Exception:
                pass
        acceptance.client.close()
    print(f'验收全部通过，证据已写入 {args.output}', flush=True)


if __name__ == '__main__':
    main()

