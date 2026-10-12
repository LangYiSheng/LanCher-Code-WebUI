"""真实本机 OpenAI SSE：失败恢复、跨模型、取消和请求用量去重。"""
from __future__ import annotations

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import time

from fastapi.testclient import TestClient
import pytest
import yaml

from test_integration import action, chat, complete, detail, project, request, submit, wait


def _usage(input_tokens, output_tokens, cache, creation, reasoning):
    return {
        'prompt_tokens': input_tokens,
        'completion_tokens': output_tokens,
        'prompt_tokens_details': {'cached_tokens': cache},
        'cache_creation_input_tokens': creation,
        'completion_tokens_details': {'reasoning_tokens': reasoning},
    }


class UsageServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self):
        super().__init__(('127.0.0.1', 0), UsageHandler)
        self.received = []
        self.guard = threading.Lock()
        self.cancel_sent = threading.Event()
        self.cancel_release = threading.Event()


class UsageHandler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *_args):
        pass

    def _frame(self, data):
        self.wfile.write(('data: ' + json.dumps(data, ensure_ascii=False) + '\n\n').encode('utf-8'))
        self.wfile.flush()

    def _usage_frame(self, value):
        self._frame({'choices': [], 'usage': value})

    def _text_frame(self, text, *, stop=False):
        self._frame({'choices': [{'index': 0, 'delta': {'content': text},
                                 'finish_reason': 'stop' if stop else None}]})

    def do_POST(self):
        if self.path != '/v1/chat/completions':
            self.send_error(404)
            return
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        with self.server.guard:
            position = len(self.server.received)
            self.server.received.append(body)
        self.close_connection = True
        if position == 0:
            # SDK 不自动重试通用 429；用户恢复会启动独立请求，原 failed 记录保留。
            error = json.dumps({'error': {'message': 'fixture rate limit', 'type': 'rate_limit_error'}}).encode()
            self.send_response(429)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Retry-After', '0')
            self.send_header('Content-Length', str(len(error)))
            self.send_header('Connection', 'close')
            self.end_headers()
            self.wfile.write(error)
            return
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.send_header('Connection', 'close')
        self.end_headers()
        try:
            if position == 1:
                # EOF 缺少 [DONE]，部分用量仍须记账，不能冒充完整回答。
                self._text_frame('这段响应将在终帧前中断。')
                self._usage_frame(_usage(40, 5, 15, 5, 2))
                return
            if position == 2:
                self._text_frame('恢复重试成功。', stop=True)
                self._usage_frame(_usage(70, 10, 20, 5, 4))
                final_usage = _usage(100, 20, 30, 10, 8)
            elif position == 3:
                self._text_frame('第二个模型成功。', stop=True)
                self._usage_frame(_usage(150, 30, 40, 12, 9))
                final_usage = _usage(200, 40, 50, 15, 12)
            elif position == 4:
                self._text_frame('这轮保持打开，等待用户取消。')
                self._usage_frame(_usage(60, 6, 12, 3, 2))
                self.server.cancel_sent.set()
                self.server.cancel_release.wait(10)
                return
            else:
                self._text_frame('测试收到意外额外请求。', stop=True)
                final_usage = _usage(1, 1, 0, 0, 0)
            # 同一请求重复累计帧，SDK 必须覆盖快照，不能把帧当作额外用量。
            self._usage_frame(final_usage)
            self._usage_frame(final_usage)
            self.wfile.write(b'data: [DONE]\n\n')
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass


@contextmanager
def _local_provider(home):
    server = UsageServer()
    config_path = home / '.lancher' / 'lancher.yaml'
    config = yaml.safe_load(config_path.read_text(encoding='utf-8'))
    config['providers']['test']['base_url'] = f'http://127.0.0.1:{server.server_port}/v1'
    config['providers']['test']['timeout_seconds'] = 15
    config_path.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding='utf-8')
    thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': 0.02}, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.cancel_release.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        assert not thread.is_alive(), '本机 fixture HTTP 服务没有关闭。'


def _records(client, identity):
    async def read_records():
        manager = client.app.state.manager
        return manager.store.requests(chat_id=identity)
    return client.portal.call(read_records)


def _summary(value, *, count, completed, incomplete, input_tokens, output_tokens, cache, creation, reasoning):
    assert value['request_count'] == count
    assert value['completed_request_count'] == completed
    assert value['incomplete_request_count'] == incomplete
    assert value['input_tokens'] == input_tokens
    assert value['output_tokens'] == output_tokens
    assert value['cached_input_tokens'] == cache
    assert value['cache_creation_input_tokens'] == creation
    assert value['reasoning_output_tokens'] == reasoning


def test_native_http_retry_switch_model_and_cancel_keep_unique_usage_records(isolated):
    from lancher_code.providers.openai import OpenAIProvider
    from webui.api import create_app
    root, home, workspace = isolated
    with _local_provider(home) as upstream:
        # 不注入 Provider：使用 SDK 的默认 OpenAIProvider 与真实 HTTP/SSE 解析。
        with TestClient(create_app(root=root, user_home=home, enable_mcp=False),
                        raise_server_exceptions=False) as client:
            identity = chat(client, project(client, workspace))
            prompt = '恢复本机模型请求'
            submit(client, identity, prompt)
            failed = complete(client, identity)
            assert failed['status'] == 'failed'
            session_id = failed['sdk_session_id']
            failed_record, = _records(client, identity)
            assert failed_record['status'] == 'failed'
            assert failed_record['usage']['input_tokens'] is None
            assert failed['usage']['answer']['request_count'] == 1
            assert failed['usage']['answer']['incomplete_request_count'] == 1
            assert failed['usage']['answer']['usage']['input_tokens'] is None
            time.sleep(0.05)
            assert len(upstream.received) == 1, '固定 SDK 的通用 429 没有自动重试。'
            assert isinstance(client.app.state.manager.owners[identity].agent._runner._models.provider,
                              OpenAIProvider)

            submit(client, identity, prompt)
            interrupted = complete(client, identity)
            assert interrupted['status'] == 'failed' and interrupted['sdk_session_id'] == session_id
            incomplete_record, = [row for row in _records(client, identity) if row['status'] == 'incomplete']
            assert incomplete_record['usage']['is_final'] is False
            assert incomplete_record['usage']['input_tokens'] == 40
            _summary(interrupted['usage']['answer'], count=1, completed=0, incomplete=1,
                     input_tokens=40, output_tokens=5, cache=15, creation=5, reasoning=2)

            # 明确模拟用户重新提交恢复；不声称 SDK 会自动重试 HTTP 错误或 EOF。
            submit(client, identity, prompt)
            recovered = complete(client, identity)
            assert recovered['status'] == 'completed' and recovered['sdk_session_id'] == session_id
            assert recovered['result']['text'] == '恢复重试成功。'
            _summary(recovered['usage']['answer'], count=1, completed=1, incomplete=0,
                     input_tokens=100, output_tokens=20, cache=30, creation=10, reasoning=8)
            _summary(recovered['usage']['session'], count=3, completed=1, incomplete=2,
                     input_tokens=140, output_tokens=25, cache=45, creation=15, reasoning=10)

            action(client, identity, 'model', model_ref='test/two')
            submit(client, identity, '切换模型后继续同一会话')
            switched = complete(client, identity)
            assert switched['status'] == 'completed' and switched['sdk_session_id'] == session_id
            assert switched['model_ref'] == 'test/two'
            assert switched['result']['text'] == '第二个模型成功。'
            _summary(switched['usage']['answer'], count=1, completed=1, incomplete=0,
                     input_tokens=200, output_tokens=40, cache=50, creation=15, reasoning=12)
            for scope in ('session', 'project', 'server'):
                _summary(switched['usage'][scope], count=4, completed=2, incomplete=2,
                         input_tokens=340, output_tokens=65, cache=95, creation=30, reasoning=22)

            submit(client, identity, '取消正在读取的本机 SSE')
            assert upstream.cancel_sent.wait(10)
            waiting = wait(client, identity, lambda row: row['usage']['answer']['input_tokens'] == 60)
            assert waiting['status'] == 'running'
            request(client, 'POST', f'/api/chats/{identity}/stop', json={'scope': 'turn'})
            upstream.cancel_release.set()
            cancelled = complete(client, identity)
            assert cancelled['status'] == 'cancelled' and cancelled['sdk_session_id'] == session_id
            _summary(cancelled['usage']['answer'], count=1, completed=0, incomplete=1,
                     input_tokens=60, output_tokens=6, cache=12, creation=3, reasoning=2)
            for scope in ('session', 'project', 'server'):
                _summary(cancelled['usage'][scope], count=5, completed=2, incomplete=3,
                         input_tokens=400, output_tokens=71, cache=107, creation=33, reasoning=24)
                # 缓存包含在 input，推理包含在 output；总量为 471，不能再次相加。
                assert cancelled['usage'][scope]['input_tokens'] + cancelled['usage'][scope]['output_tokens'] == 471
                # f3329bc 同批 input/cache 样本保留估算率，失败未知样本不压低分母。
                assert cancelled['usage'][scope]['cache_hit_ratio'] == pytest.approx(107 / 400)
                assert cancelled['usage'][scope]['cache_ratio_estimated'] is True
                assert cancelled['usage'][scope]['cache_ratio_request_count'] == 4

            records = _records(client, identity)
            ids = {row['request_id'] for row in records}
            assert len(records) == len(ids) == len(upstream.received) == 5
            assert {row['session_id'] for row in records} == {session_id}
            assert sorted(row['status'] for row in records) == [
                'cancelled', 'completed', 'completed', 'failed', 'incomplete']
            assert [row['model'] for row in records].count('fixture-one') == 3
            assert [row['model'] for row in records].count('fixture-two') == 2
            assert [body['model'] for body in upstream.received] == ['fixture-one'] * 3 + ['fixture-two'] * 2
            assert all(body['stream_options'] == {'include_usage': True} for body in upstream.received)
            assert all(body['stream'] is True for body in upstream.received)
            assert failed_record['request_id'] in ids and incomplete_record['request_id'] in ids
            assert next(row for row in records if row['status'] == 'cancelled')['usage']['is_final'] is False

            # 反复 API 快照、目录刷新、释放并读取持久化历史都不能膨胀去重账本。
            original_usage = cancelled['usage']
            for _ in range(3):
                request(client, 'GET', '/api/bootstrap')
                assert detail(client, identity)['usage'] == original_usage
            action(client, identity, 'release')
            restored = detail(client, identity)
            assert restored['sdk_session_id'] == session_id and restored['usage'] == original_usage
            assert {row['request_id'] for row in _records(client, identity)} == ids
            assert len([row for row in restored['messages'] if row['role'] == 'user']) == 5