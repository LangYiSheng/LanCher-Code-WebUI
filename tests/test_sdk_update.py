"""新版 SDK 推理控制、模型发现与缓存口径；仅使用临时配置和本机 HTTP。"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
from urllib.parse import parse_qs, urlsplit

import pytest
import yaml

from provider_helpers import Reply
from test_integration import action, chat, complete, detail, project, request, submit, wait


def _yaml_path(isolated):
    return isolated[1] / '.lancher' / 'lancher.yaml'


def _write_config(isolated, transform):
    path = _yaml_path(isolated)
    raw = yaml.safe_load(path.read_text(encoding='utf-8'))
    transform(raw)
    path.write_text(yaml.safe_dump(raw, allow_unicode=True, sort_keys=False), encoding='utf-8')
    return raw


def _declare_effort(isolated):
    from lancher_code.providers.metadata import ModelCapabilities, ModelMetadata, connection_fingerprint, serialize_metadata
    def transform(raw):
        provider = raw['providers']['test']
        fingerprint = connection_fingerprint(provider['protocol'], provider['base_url'], provider['api_key'])
        for identity, levels in (('one', ('low', 'high')), ('two', ('low',))):
            model = provider['models'][identity]
            metadata = ModelMetadata(model['model_name'], fingerprint, '2026-10-12T00:00:00Z',
                capabilities=ModelCapabilities(effort_levels=levels, endpoints=('chat_completions',)))
            model['metadata'] = serialize_metadata(metadata)
    _write_config(isolated, transform)


def test_effort_is_draft_control_then_native_persisted_and_adapts_to_new_model(client, isolated, provider):
    _declare_effort(isolated)
    project_id = project(client, isolated[2])
    created = request(client, 'POST', '/api/chats', json={'project_id': project_id, 'reasoning_effort': 'high'})
    identity = created['id']
    assert created['draft'] and created['reasoning_effort'] == 'high'
    first = detail(client, identity)
    assert first['effort_known'] and first['effort_levels'] == ['auto', 'low', 'high']
    assert first['sdk_session_id'] is None
    assert request(client, 'GET', f'/api/projects/{project_id}/impact')['conversation_count'] == 0
    submit(client, identity, '高强度首条任务')
    finished = complete(client, identity)
    session_id = finished['sdk_session_id']
    assert finished['status'] == 'completed' and finished['reasoning_effort'] == 'high'
    assert provider.requests[-1]['reasoning_effort'] == 'high'
    assert provider.requests[-1]['api_mode'] == 'chat_completions'
    action(client, identity, 'release')
    restored = detail(client, identity)
    assert restored['sdk_session_id'] == session_id and restored['reasoning_effort'] == 'high'
    fresh = chat(client, project_id, '其他草稿保持自动')
    assert detail(client, fresh)['reasoning_effort'] == 'auto'

    action(client, identity, 'model', model_ref='test/two')
    switched = detail(client, identity)
    assert switched['sdk_session_id'] == session_id
    assert switched['reasoning_effort'] == 'auto' and switched['effort_levels'] == ['auto', 'low']
    rejected = client.post(f'/api/chats/{identity}/actions', json={'action': 'effort', 'effort': 'high'})
    assert rejected.status_code == 409 and '推理' in rejected.json()['detail']
    assert detail(client, identity)['reasoning_effort'] == 'auto'
    submit(client, identity, '第二模型延续同一历史')
    assert complete(client, identity)['sdk_session_id'] == session_id
    assert provider.requests[-1]['reasoning_effort'] == 'auto'
    assert yaml.safe_load(_yaml_path(isolated).read_text(encoding='utf-8'))['default_model'] == 'test/one'


def test_effort_slash_completion_and_busy_rejection_keep_current_choice(client, isolated, provider):
    identity = chat(client, project(client, isolated[2]))
    picker = request(client, 'POST', f'/api/chats/{identity}/commands', json={'text': '/effort'})
    assert picker['ui_action'] == 'effort_picker'
    completed = request(client, 'GET', '/api/commands/complete', params={'chat_id': identity, 'text': '/effort '})
    assert completed['candidates']
    assert detail(client, identity)['effort_known'] is False
    request(client, 'POST', f'/api/chats/{identity}/commands', json={'text': '/effort high'})
    assert detail(client, identity)['draft'] and detail(client, identity)['reasoning_effort'] == 'high'
    for text in ('/effort none', '/effort off', '/effort high 不应作为任务正文'):
        assert client.post(f'/api/chats/{identity}/commands', json={'text': text}).status_code == 400
    assert provider.requests == []
    gate = threading.Event()
    provider.plans['推理控制忙时测试'] = [Reply(text='完成', gate=gate)]
    try:
        submit(client, identity, '推理控制忙时测试')
        wait(client, identity, lambda _: bool(provider.requests))
        assert client.post(f'/api/chats/{identity}/actions', json={'action': 'effort', 'effort': 'low'}).status_code == 409
        assert client.post(f'/api/chats/{identity}/commands', json={'text': '/effort low'}).status_code == 409
        assert detail(client, identity)['reasoning_effort'] == 'high'
    finally:
        gate.set()
    assert complete(client, identity)['status'] == 'completed'
    request(client, 'POST', f'/api/chats/{identity}/commands', json={'text': '/effort auto'})
    assert detail(client, identity)['reasoning_effort'] == 'auto'


class ModelsHandler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_GET(self):
        self.server.received.append({'path': self.path, 'authorization': self.headers.get('Authorization')})
        status = self.server.status
        body = {'error': 'local fixture error'}
        if status == 200:
            models = self.server.models
            if self.server.paginated:
                cursor = parse_qs(urlsplit(self.path).query).get('after_id', [None])[0]
                body = {'data': models[:1], 'has_more': True, 'last_id': models[0]['id']} if cursor is None else {'data': models[1:], 'has_more': False}
            else:
                body = {'data': models}
        encoded = json.dumps(body).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


@contextmanager
def _upstream(isolated):
    server = ThreadingHTTPServer(('127.0.0.1', 0), ModelsHandler)
    server.daemon_threads = True
    server.received, server.status, server.paginated = [], 200, False
    server.models = [
        {'id': 'fixture-one', 'display_name': '端点名字', 'context_window': 8192, 'max_output_tokens': 2048,
         'supported_endpoints': ['chat_completions'], 'capabilities': {'effort': {'supported_levels': ['low', 'high']}}},
        {'id': 'fixture-two', 'context_window': 16384, 'max_output_tokens': 2048},
        {'id': 'new-model', 'display_name': '发现的新模型', 'context_window': 32768, 'max_output_tokens': 4096},
    ]
    server.base_url = f'http://127.0.0.1:{server.server_port}/v1'
    def transform(raw):
        provider = raw['providers']['test']
        provider['base_url'] = server.base_url
        provider['models']['one'].update(display_name='手动显示名', context_window=65536, max_output_tokens=1024,
                                         thinking={'enabled': True, 'budget_tokens': 2048})
        provider['models']['two'].update(base_url='http://127.0.0.1:9/v1', api_key='independent-model-secret')
    _write_config(isolated, transform)
    thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': 0.02}, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        assert not thread.is_alive(), '本机模型列表 fixture 未退出。'


def _settings(client, project_id):
    return request(client, 'GET', '/api/settings', params={'project_id': project_id})


def _discover_payload(client, project_id):
    snapshot = _settings(client, project_id)
    return {'provider_id': 'test', 'provider': deepcopy(snapshot['config']['providers']['test']),
            'project_id': project_id, 'revision': snapshot['revision']}


def _discover(client, payload, **kwargs):
    return request(client, 'POST', '/api/settings/model-discovery', json={**payload, **kwargs})


def _merge(client, payload, result, selected=('new-model',), **kwargs):
    return request(client, 'POST', '/api/settings/model-discovery/merge',
                   json={**payload, 'discovery_id': result['discovery_id'], 'selected_ids': list(selected), **kwargs})


def test_discovery_real_http_preserves_manual_models_and_requires_explicit_save(client, isolated):
    with _upstream(isolated) as server:
        project_id = project(client, isolated[2])
        identity = chat(client, project_id)
        payload = _discover_payload(client, project_id)
        original = _yaml_path(isolated).read_bytes()
        result = _discover(client, payload)
        assert not result['cached'] and not result['stale']
        assert result['existing'] == ['fixture-one']
        assert {row['id'] for row in result['models']} == {'fixture-one', 'fixture-two', 'new-model'}
        assert server.received == [{'path': '/v1/models', 'authorization': 'Bearer fixture-secret-never-exposed'}]
        merged = _merge(client, payload, result)
        assert merged['added'] == 1 and merged['updated'] == 1
        models = merged['provider']['models']
        assert models['one']['display_name'] == '手动显示名'
        assert models['one']['context_window'] == 65536 and models['one']['max_output_tokens'] == 1024
        assert models['one']['metadata']['context_window'] == 8192
        assert models['two']['base_url'] == 'http://127.0.0.1:9/v1' and models['two']['metadata'] is None
        assert models['two']['api_key_configured'] and not models['two']['api_key']
        assert 'fixture-secret-never-exposed' not in json.dumps(result | merged)
        assert 'independent-model-secret' not in json.dumps(result | merged)
        assert _yaml_path(isolated).read_bytes() == original
        assert detail(client, identity)['model_ref'] == 'test/one'
        snapshot = _settings(client, project_id)
        data = {'providers': {**snapshot['config']['providers'], 'test': merged['provider']},
                'default_model': snapshot['config']['default_model']}
        saved = request(client, 'PATCH', '/api/settings', json={'domain': 'models', 'scope': 'global',
                         'project_id': project_id, 'revision': snapshot['revision'], 'data': data})
        assert saved['saved']
        raw = yaml.safe_load(_yaml_path(isolated).read_text(encoding='utf-8'))
        assert raw['default_model'] == 'test/one'
        assert raw['providers']['test']['api_key'] == 'fixture-secret-never-exposed'
        assert raw['providers']['test']['models']['two']['api_key'] == 'independent-model-secret'
        assert 'thinking' not in raw['providers']['test']['models']['one']
        assert 'new-model' in raw['providers']['test']['models']
        assert detail(client, identity)['model_ref'] == 'test/one'


def test_discovery_ticket_rejects_connection_scope_revision_and_expiry(client, isolated):
    with _upstream(isolated):
        project_id = project(client, isolated[2])
        other = isolated[0].parent / 'other-project'
        other.mkdir()
        other_id = project(client, other)
        payload = _discover_payload(client, project_id)
        result = _discover(client, payload)
        merge_body = {**payload, 'discovery_id': result['discovery_id'], 'selected_ids': ['new-model']}
        for changed in ({'project_id': other_id}, {'provider_id': 'different'},
                        {'provider': {**payload['provider'], 'api_key': 'another-secret'}},
                        {'provider': {**payload['provider'], 'base_url': payload['provider']['base_url'] + '/changed'}}):
            assert client.post('/api/settings/model-discovery/merge', json={**merge_body, **changed}).status_code == 409
        _write_config(isolated, lambda raw: raw.update(ui={'show_timestamps': True}))
        assert client.post('/api/settings/model-discovery/merge', json=merge_body).status_code == 409
        fresh = _discover_payload(client, project_id)
        next_result = _discover(client, fresh)
        service = client.app.state.discovery
        expiration = service.tickets[next_result['discovery_id']].expires
        service.clock = lambda: expiration + 1
        assert client.post('/api/settings/model-discovery/merge', json={**fresh,
            'discovery_id': next_result['discovery_id'], 'selected_ids': ['new-model']}).status_code == 409


def test_discovery_sdk_cache_stale_refresh_and_auth_never_cross_connection(client, isolated):
    with _upstream(isolated) as server:
        project_id = project(client, isolated[2])
        payload = _discover_payload(client, project_id)
        first = _discover(client, payload)
        cached = _discover(client, payload)
        assert cached['cached'] and not cached['stale'] and len(server.received) == 1
        server.status = 500
        stale = _discover(client, payload, refresh=True)
        assert stale['cached'] and stale['stale'] and stale['models'] == first['models']
        assert len(server.received) == 2
        changed = {**payload, 'provider': {**payload['provider'], 'api_key': 'new-identity-secret'}}
        response = client.post('/api/settings/model-discovery', json={**changed, 'refresh': True})
        assert response.status_code >= 400 and 'models' not in response.json()
        assert 'new-identity-secret' not in response.text
        server.status = 401
        unauthorized = client.post('/api/settings/model-discovery', json={**payload, 'refresh': True})
        assert unauthorized.status_code == 401 and 'models' not in unauthorized.json()
        assert 'fixture-secret-never-exposed' not in unauthorized.text
        assert _settings(client, project_id)['config']['default_model'] == 'test/one'


def test_unsaved_provider_without_models_discovers_pages_and_preserves_env_reference(client, isolated, monkeypatch):
    monkeypatch.setenv('SDK_UPDATE_FIXTURE_KEY', 'temporary-env-model-secret')
    with _upstream(isolated) as server:
        server.paginated = True
        project_id = project(client, isolated[2])
        snapshot = _settings(client, project_id)
        original = _yaml_path(isolated).read_bytes()
        new_provider = {'name': '未保存供应商', 'protocol': 'openai', 'base_url': server.base_url,
                        'api_key': '${SDK_UPDATE_FIXTURE_KEY}', 'models': {}}
        payload = {'provider_id': 'new', 'provider': new_provider, 'project_id': project_id,
                   'revision': snapshot['revision']}
        discovered = _discover(client, payload)
        assert len(discovered['models']) == 3 and discovered['existing'] == []
        assert len(server.received) == 2 and 'after_id=fixture-one' in server.received[1]['path']
        assert all(row['authorization'] == 'Bearer temporary-env-model-secret' for row in server.received)
        merged = _merge(client, payload, discovered, selected=('new-model',))
        assert merged['added'] == 1 and merged['updated'] == 0
        assert _yaml_path(isolated).read_bytes() == original
        assert 'temporary-env-model-secret' not in json.dumps(discovered | merged)
        # 发现结果公开密钥为空；未保存的新供应商仍保留编辑器原有 ENV 引用再显式保存。
        edited = {**merged['provider'], 'api_key': new_provider['api_key']}
        request(client, 'PATCH', '/api/settings', json={'domain': 'models', 'project_id': project_id,
            'revision': snapshot['revision'], 'data': {'providers': {**snapshot['config']['providers'], 'new': edited},
                                                     'default_model': 'test/one'}})
        raw = yaml.safe_load(_yaml_path(isolated).read_text(encoding='utf-8'))
        assert raw['providers']['new']['api_key'] == '${SDK_UPDATE_FIXTURE_KEY}'
        assert raw['default_model'] == 'test/one'


def test_sdk_cache_rate_uses_only_paired_valid_samples_and_marks_estimate():
    from lancher_code.usage.ledger import RequestUsageRecord, summarize_records
    from lancher_code.usage.models import MessageUsage
    def record(identity, usage):
        return RequestUsageRecord(identity, 'fixture-run', 'openai', 'fixture-model', status='completed', usage=usage)
    summary = summarize_records([
        record('good', MessageUsage(input_tokens=50, output_tokens=10, cached_input_tokens=20)),
        record('unpaired', MessageUsage(output_tokens=12, cached_input_tokens=4)),
        record('invalid', MessageUsage(input_tokens=10, output_tokens=1, cached_input_tokens=20)),
    ])
    assert summary.cache_hit_ratio == pytest.approx(20 / 50)
    assert summary.cache_ratio_estimated and summary.cache_ratio_request_count == 1
    assert summary.request_count == 3 and summary.invalid_request_count == 1
    assert summarize_records([record('unknown', MessageUsage())]).cache_hit_ratio is None
    assert summarize_records([record('zero', MessageUsage(input_tokens=0, cached_input_tokens=0))]).cache_hit_ratio is None


def test_discovery_merge_keeps_clear_and_inheritance_intent_until_saved(client, isolated):
    with _upstream(isolated):
        def old_values(raw):
            provider = raw['providers']['test']
            provider['api_mode'] = 'responses'
            provider['models']['one'].update(api_mode='responses', display_name='旧名称',
                base_url='http://127.0.0.1:9/old/v1', api_key='old-model-only-secret')
        _write_config(isolated, old_values)
        project_id = project(client, isolated[2])
        payload = _discover_payload(client, project_id)
        payload['provider']['api_mode'] = 'auto'
        payload['provider']['models']['one'].update(api_mode=None, display_name='', base_url=None,
                                                   api_key=None, api_key_clear=True)
        original = _yaml_path(isolated).read_bytes()
        discovered = _discover(client, payload)
        merged = _merge(client, payload, discovered)
        edited = merged['provider']
        model = edited['models']['one']
        assert edited['api_mode'] == 'auto'
        assert model['api_mode'] is None and model['base_url'] is None and model['display_name'] == ''
        assert model['api_key_clear'] is True and 'api_key' not in model
        assert 'old-model-only-secret' not in json.dumps(merged)
        assert _yaml_path(isolated).read_bytes() == original
        snapshot = _settings(client, project_id)
        request(client, 'PATCH', '/api/settings', json={'domain': 'models', 'project_id': project_id,
            'revision': snapshot['revision'], 'data': {'providers': {**snapshot['config']['providers'], 'test': edited},
                                                      'default_model': 'test/one'}})
        raw = yaml.safe_load(_yaml_path(isolated).read_text(encoding='utf-8'))
        saved = raw['providers']['test']['models']['one']
        # YAML 可以保留显式 auto/None；SDK 读回必须实际恢复继承，而非依赖省略格式。
        assert raw['providers']['test'].get('api_mode', 'auto') == 'auto'
        assert all(saved.get(key) is None for key in ('api_mode', 'base_url', 'api_key'))
        assert saved.get('display_name', '') == '' and 'api_key_clear' not in saved
        config = client.app.state.manager.configuration.get_config()
        assert config.providers['test'].api_mode == 'auto'
        restored = config.providers['test'].models['one']
        assert restored.api_mode is None and restored.base_url is None and restored.api_key is None
        assert restored.display_name == '' and raw['default_model'] == 'test/one'


@pytest.mark.parametrize('invalid', ['missing_revision', 'extra_field'])
def test_validation_errors_never_echo_model_api_keys(client, isolated, invalid):
    project_id = project(client, isolated[2])
    payload = _discover_payload(client, project_id)
    payload['provider']['api_key'] = 'validation-input-secret-must-not-echo'
    if invalid == 'missing_revision':
        payload.pop('revision')
    else:
        payload['unexpected_secret'] = 'validation-extra-secret-must-not-echo'
    response = client.post('/api/settings/model-discovery', json=payload)
    assert response.status_code == 422
    assert response.json() == {'detail': '请求参数格式无效，请检查必填项和选项。'}
    assert 'validation-input-secret-must-not-echo' not in response.text
    assert 'validation-extra-secret-must-not-echo' not in response.text
    assert 'input' not in response.json()


def test_auth_invalidates_tickets_and_forces_fresh_until_success(client, isolated):
    with _upstream(isolated) as server:
        project_id = project(client, isolated[2])
        payload = _discover_payload(client, project_id)
        first = _discover(client, payload)
        old_merge = {**payload, 'discovery_id': first['discovery_id'], 'selected_ids': ['new-model']}
        assert len(server.received) == 1
        server.status = 401
        refused = client.post('/api/settings/model-discovery', json={**payload, 'refresh': True})
        assert refused.status_code == 401 and 'models' not in refused.json()
        assert client.post('/api/settings/model-discovery/merge', json=old_merge).status_code == 409
        # 不带 refresh 重开也必须远端校验，不能返回 SDK 内仍存在的旧缓存。
        assert client.post('/api/settings/model-discovery', json=payload).status_code == 401
        assert len(server.received) == 3
        server.status = 500
        stale = client.post('/api/settings/model-discovery', json=payload)
        assert stale.status_code == 401 and 'models' not in stale.json()
        assert len(server.received) == 4
        server.status = 200
        recovered = _discover(client, payload)
        assert not recovered['cached'] and not recovered['stale'] and len(server.received) == 5
        assert _discover(client, payload)['cached'] and len(server.received) == 5
        assert client.post('/api/settings/model-discovery/merge', json=old_merge).status_code == 409
