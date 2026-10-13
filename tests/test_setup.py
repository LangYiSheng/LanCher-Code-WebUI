"""首次引导、字段错误及领域隔离只操作专用临时配置。"""
import copy
import json
import threading

import pytest
import yaml

from lancher_code.config.loader import load_config
from lancher_code.providers.discovery import ModelDiscoveryResult, discovery_connection
from lancher_code.providers.metadata import connection_fingerprint
from webui.configuration import ConfigurationError, ConfigurationService
from webui.validation import validate_domain, validate_mcp, validate_models, validate_rules
from provider_helpers import Reply


def config_path(isolated):
    return isolated[1] / '.lancher' / 'lancher.yaml'


def write_config(isolated, raw):
    config_path(isolated).write_text(yaml.safe_dump(raw, allow_unicode=True), encoding='utf-8')


def service(isolated):
    return ConfigurationService(isolated[0], user_home=isolated[1])


def test_required_setup_saves_all_domains_and_is_immediately_ready(isolated):
    path = config_path(isolated)
    original = yaml.safe_load(path.read_text(encoding='utf-8'))
    path.unlink()
    current = service(isolated)
    before = current.setup_snapshot()
    assert before['state'] == 'required'
    assert before['config_exists'] is False
    assert set(before['data']) == {'models', 'ui', 'runtime', 'execution'}
    data = before['data']
    data['models'] = {key: original[key] for key in ('providers', 'default_model')}
    data['ui']['theme'] = 'light'
    data['runtime']['tool_loop_limit'] = 23
    result = current.save({'domain': 'setup', 'revision': before['revision'], 'data': data})
    assert result['saved'] and result['snapshot']['state'] == 'ready'
    assert result['snapshot']['config_exists'] is True
    loaded = load_config(path)
    assert loaded.ui.theme == 'light' and loaded.runtime.tool_loop_limit == 23
    assert current.snapshot()['configured']
    assert 'fixture-secret-never-exposed' not in json.dumps(result)


def test_provider_without_models_remains_required_and_keeps_its_connection(isolated):
    raw = yaml.safe_load(config_path(isolated).read_text(encoding='utf-8'))
    raw['providers']['test']['models'] = {}
    write_config(isolated, raw)
    before = service(isolated).setup_snapshot()
    assert before['state'] == 'required'
    assert before['config_exists'] is True
    assert before['data']['models']['providers']['test']['name'] == '测试'
    assert before['data']['models']['providers']['test']['api_key_configured']


def test_repair_snapshot_keeps_masked_model_drafts_and_reports_many_domains(isolated):
    raw = yaml.safe_load(config_path(isolated).read_text(encoding='utf-8'))
    raw['providers']['test']['base_url'] = ''
    raw['default_model'] = 'test/missing'
    raw['ui'] = {'theme': 'wrong', 'show_timestamps': 'yes'}
    raw['runtime'] = {'tool_loop_limit': 0, 'execution_access': 'wrong'}
    raw['execution'] = {'limits': {'max_processes': -1, 'output_limit_bytes': 1}}
    write_config(isolated, raw)
    before = service(isolated).setup_snapshot()
    assert before['state'] == 'repair'
    assert set(row['domain'] for row in before['issues']) == {'models', 'ui', 'runtime', 'execution'}
    assert len(before['issues']) >= 7
    assert before['data']['models']['providers']['test']['models']['one']['model_name'] == 'fixture-one'
    assert 'fixture-secret-never-exposed' not in json.dumps(before)


@pytest.mark.parametrize('text', ['providers: [broken', '- a\n- b\n', 'providers: wrong\n', 'ui: wrong\n'])
def test_unreadable_setup_cannot_overwrite_original_configuration(isolated, text):
    path = config_path(isolated)
    path.write_text(text, encoding='utf-8')
    original = path.read_bytes()
    current = service(isolated)
    before = current.setup_snapshot()
    assert before['state'] == 'unreadable' and before['data'] is None
    with pytest.raises(ConfigurationError):
        current.save({'domain': 'setup', 'revision': before['revision'], 'data': {}})
    assert path.read_bytes() == original


@pytest.mark.parametrize('case', ['provider_id', 'model_id', 'provider_numeric_id', 'legacy_runtime', 'execution_limit', 'execution_key'])
def test_uneditable_legacy_or_identifier_structure_is_unreadable(isolated, case):
    raw = yaml.safe_load(config_path(isolated).read_text(encoding='utf-8'))
    if case == 'provider_id':
        raw['providers']['bad/id'] = raw['providers'].pop('test')
    elif case == 'provider_numeric_id':
        raw['providers'][7] = raw['providers'].pop('test')
    elif case == 'model_id':
        raw['providers']['test']['models']['bad/id'] = raw['providers']['test']['models'].pop('one')
    elif case == 'legacy_runtime':
        raw['runtime']['permission_mode'] = 'legacy'
    elif case == 'execution_limit':
        raw['execution'] = {'limits': {'unknown_limit': 3}}
    else:
        raw['execution'] = {'unsupported_option': True}
    write_config(isolated, raw)
    before = service(isolated).setup_snapshot()
    assert before['state'] == 'unreadable' and before['data'] is None and before['issues']


def test_setup_revision_ignores_unrelated_broken_mcp_and_permissions(isolated):
    current = service(isolated)
    before = current.setup_snapshot()
    (isolated[1] / '.lancher' / 'mcp.yaml').write_text('mcp_servers: [broken', encoding='utf-8')
    (isolated[1] / '.lancher' / 'permissions.yaml').write_text('rules: [broken', encoding='utf-8')
    assert current.setup_snapshot()['revision'] == before['revision']
    result = current.save({'domain': 'setup', 'revision': before['revision'], 'data': before['data']})
    assert result['snapshot']['state'] == 'ready'


def test_setup_merge_preserves_unknown_fields_and_secret_templates(isolated):
    raw = yaml.safe_load(config_path(isolated).read_text(encoding='utf-8'))
    raw['custom_top_level'] = {'keep': 'yes'}
    raw['providers']['test']['custom_provider'] = 17
    raw['providers']['test']['api_key'] = '${SETUP_EXISTING_KEY}'
    raw['providers']['test']['models']['one'].update(custom_model={'keep': True}, api_key='model-secret-never-exposed')
    raw['ui'] = {'future_ui_option': 42}
    raw['runtime']['future_runtime_option'] = 99
    write_config(isolated, raw)
    current = service(isolated)
    before = current.setup_snapshot()
    edited = copy.deepcopy(before['data'])
    edited['models']['providers']['test']['name'] = '改名'
    edited['ui']['theme'] = 'light'
    result = current.save({'domain': 'setup', 'revision': before['revision'], 'data': edited})
    saved = yaml.safe_load(config_path(isolated).read_text(encoding='utf-8'))
    assert saved['custom_top_level'] == raw['custom_top_level']
    assert saved['providers']['test']['custom_provider'] == 17
    assert saved['providers']['test']['api_key'] == '${SETUP_EXISTING_KEY}'
    assert saved['providers']['test']['models']['one']['custom_model'] == {'keep': True}
    assert saved['providers']['test']['models']['one']['api_key'] == 'model-secret-never-exposed'
    assert 'api_key' not in saved['providers']['test']['models']['two']
    assert saved['ui']['future_ui_option'] == 42 and saved['runtime']['future_runtime_option'] == 99
    assert 'model-secret-never-exposed' not in json.dumps(result)


def test_setup_validation_is_atomic_and_rejects_stale_revisions(isolated):
    current = service(isolated)
    before = current.setup_snapshot()
    original = config_path(isolated).read_bytes()
    edited = copy.deepcopy(before['data'])
    edited['ui'].update(theme='wrong', show_timestamps='yes')
    edited['runtime']['tool_loop_limit'] = 0
    with pytest.raises(ConfigurationError) as rejected:
        current.save({'domain': 'setup', 'revision': before['revision'], 'data': edited})
    assert len(rejected.value.issues) == 3
    assert config_path(isolated).read_bytes() == original
    with pytest.raises(ConfigurationError) as conflict:
        current.save({'domain': 'setup', 'revision': 'stale', 'data': before['data']})
    assert conflict.value.status == 409


def test_unrelated_broken_domains_do_not_block_normal_saves_or_snapshots(isolated):
    current = service(isolated)
    home_config = isolated[1] / '.lancher'
    (home_config / 'mcp.yaml').write_text('mcp_servers: [broken', encoding='utf-8')
    (home_config / 'permissions.yaml').write_text('rules: [broken', encoding='utf-8')
    before = current.snapshot(isolated[2])
    assert {'global_mcp', 'user_rules'} <= before['domain_errors'].keys()
    assert 'global_mcp' not in before and 'user_rules' not in before
    assert before['project_mcp'] == {} and before['project_rules'] == []
    saved = current.save({'domain': 'ui', 'revision': before['revision'], 'data': {'theme': 'light'}}, isolated[2])
    assert saved['saved'] and saved['snapshot']['config']['ui']['theme'] == 'light'
    again = current.snapshot(isolated[2])
    mcp = current.save({'domain': 'mcp', 'scope': 'project', 'revision': again['revision'],
                        'data': {'python': {'type': 'stdio', 'command': 'python'}}}, isolated[2])
    assert mcp['saved'] and 'user_rules' in mcp['snapshot']['domain_errors']
    rules = current.save({'domain': 'rules', 'scope': 'project', 'revision': mcp['revision'],
                          'data': [{'match': 'protected', 'result': 'deny'}]}, isolated[2])
    assert rules['saved'] and len(rules['snapshot']['project_rules']) == 1


def test_normal_save_rejects_bad_other_main_domains_without_writing(isolated):
    raw = yaml.safe_load(config_path(isolated).read_text(encoding='utf-8'))
    raw['runtime']['tool_loop_limit'] = 0
    write_config(isolated, raw)
    current = service(isolated)
    before = current.snapshot()
    assert 'runtime' in before['domain_errors'] and 'runtime' not in before['config']
    original = config_path(isolated).read_bytes()
    with pytest.raises(ConfigurationError) as rejected:
        current.save({'domain': 'ui', 'revision': before['revision'], 'data': {'theme': 'light'}})
    assert rejected.value.issues[0]['domain'] == 'runtime'
    assert config_path(isolated).read_bytes() == original
    assert yaml.safe_load(config_path(isolated).read_text(encoding='utf-8'))['runtime']['tool_loop_limit'] == 0


def test_mcp_multiple_timeouts_have_safe_field_errors_before_sdk(isolated):
    current = service(isolated)
    before = current.snapshot()
    with pytest.raises(ConfigurationError) as rejected:
        current.save({'domain': 'mcp', 'scope': 'global', 'revision': before['revision'], 'data': {
            'broken': {'type': 'stdio', 'command': '', 'startup_timeout_seconds': 0,
                       'tool_timeout_seconds': -1, 'close_timeout_seconds': False,
                       'env': {'TOKEN': 'input-secret-do-not-echo'}}}})
    assert {row['path'][-1] for row in rejected.value.issues} == {
        'command', 'startup_timeout_seconds', 'tool_timeout_seconds', 'close_timeout_seconds'}
    assert 'input-secret-do-not-echo' not in json.dumps(rejected.value.issues)
    assert not (isolated[1] / '.lancher' / 'mcp.yaml').exists()


async def test_discovery_uses_setup_revision_without_loading_broken_permissions(isolated, monkeypatch):
    current = service(isolated)
    (isolated[1] / '.lancher' / 'permissions.yaml').write_text('rules: [broken', encoding='utf-8')
    before = current.setup_snapshot()
    provider = before['data']['models']['providers']['test']
    async def discover(value, *, refresh=False):
        protocol, url, key, _ = discovery_connection(value)
        return ModelDiscoveryResult((), 'fixture-time', connection_fingerprint(protocol, url, key))
    monkeypatch.setattr(current.model_discovery, 'discover', discover)
    result = await current.discover_models({'provider_id': 'test', 'provider': provider, 'revision': before['revision']})
    assert result.models == ()


def test_http_setup_schema_and_safe_multi_errors(client, isolated):
    path = config_path(isolated)
    path.unlink()
    boot = client.get('/api/bootstrap').json()
    assert boot['setup']['state'] == 'required'
    before = client.get('/api/settings', params={'domain': 'setup'}).json()
    assert before['state'] == 'required' and before['data']['models']['providers'] == {}
    data = before['data']
    data['models'] = {'providers': {'new': {'name': '', 'protocol': 'wrong', 'base_url': '',
                    'api_key': 'http-secret-never-echo', 'models': {'one': {'model_name': ''}}}}, 'default_model': ''}
    response = client.patch('/api/settings', json={'domain': 'setup', 'revision': before['revision'], 'data': data})
    assert response.status_code == 400
    assert len(response.json()['issues']) >= 5
    assert 'http-secret-never-echo' not in response.text and not path.exists()


@pytest.mark.parametrize('validator,value', [
    (validate_models, {'providers': {'p': {'name': [], 'protocol': [], 'base_url': {}, 'api_key': {}, 'models': {}}}, 'default_model': []}),
    (validate_mcp, {'p': {'type': [], 'enabled': {}, 'headers': {'TOKEN': {}}, 'tool_timeout_seconds': []}}),
    (validate_rules, [{'match': {}, 'match_kind': []}]),
    (lambda value: validate_domain('execution', value), {'command_profiles': [{'readiness': {'host': {}, 'port': []}, 'resources': []}]}),
])
def test_wrong_json_types_produce_issues_without_exception(validator, value):
    assert validator(value)


def test_mcp_query_and_fragment_remain_valid_but_userinfo_is_rejected():
    assert not validate_mcp({'service': {'type': 'http', 'url': 'https://example.test/mcp?workspace=demo#section'}})
    assert validate_mcp({'service': {'type': 'http', 'url': 'https://name:secret@example.test/mcp'}})[0]['path'] == ['service', 'url']


def test_readable_bad_mcp_fields_keep_redacted_drafts_and_can_be_repaired(isolated):
    path = isolated[1] / '.lancher' / 'mcp.yaml'
    path.write_text(yaml.safe_dump({'mcp_servers': {'repair': {'type': 'stdio', 'command': '',
                    'tool_timeout_seconds': 0, 'env': {'TOKEN': 'mcp-repair-secret-never-exposed'}}}}), encoding='utf-8')
    current = service(isolated)
    before = current.snapshot()
    assert 'global_mcp' in before and 'global_mcp' in before['domain_errors']
    assert before['global_mcp']['repair']['env']['TOKEN'] == ''
    assert 'mcp-repair-secret-never-exposed' not in json.dumps(before)
    edited = copy.deepcopy(before['global_mcp'])
    edited['repair'].update(command='python', tool_timeout_seconds=60)
    saved = current.save({'domain': 'mcp', 'scope': 'global', 'revision': before['revision'], 'data': edited})
    assert saved['saved'] and 'global_mcp' not in saved['snapshot']['domain_errors']
    assert yaml.safe_load(path.read_text(encoding='utf-8'))['mcp_servers']['repair']['env']['TOKEN'] == 'mcp-repair-secret-never-exposed'


def test_http_setup_finishes_without_a_project_and_refreshes_bootstrap(client, isolated):
    path = config_path(isolated)
    original = yaml.safe_load(path.read_text(encoding='utf-8'))
    path.unlink()
    before = client.get('/api/settings', params={'domain': 'setup'}).json()
    before['data']['models'] = {key: original[key] for key in ('providers', 'default_model')}
    response = client.patch('/api/settings', json={'domain': 'setup', 'project_id': 'missing-project',
                           'revision': before['revision'], 'data': before['data']})
    assert response.status_code == 200, response.text
    assert response.json()['saved'] and response.json()['snapshot']['state'] == 'ready'
    boot = client.get('/api/bootstrap').json()
    assert boot['setup']['state'] == 'ready' and len(boot['models']) == 2


def test_setup_write_failure_preserves_original_file_and_uses_safe_error(isolated, monkeypatch):
    current = service(isolated)
    before = current.setup_snapshot()
    original = config_path(isolated).read_bytes()
    def fail_write(*_args):
        raise OSError('write-failure-secret-do-not-echo')
    monkeypatch.setattr('webui.configuration.write_yaml_atomic', fail_write)
    with pytest.raises(ConfigurationError) as rejected:
        current.save({'domain': 'setup', 'revision': before['revision'], 'data': before['data']})
    assert config_path(isolated).read_bytes() == original
    assert 'write-failure-secret-do-not-echo' not in str(rejected.value)
    assert 'write-failure-secret-do-not-echo' not in json.dumps(rejected.value.issues)


@pytest.mark.parametrize('source', ['setup', 'ordinary'])
async def test_discovery_rechecks_same_revision_source_after_network(isolated, monkeypatch, source):
    current = service(isolated)
    setup = current.setup_snapshot()
    revision = setup['revision'] if source == 'setup' else current.snapshot()['revision']
    async def discover(value, *, refresh=False):
        (isolated[1] / '.lancher' / 'permissions.yaml').write_text('rules: [broken', encoding='utf-8')
        protocol, url, key, _ = discovery_connection(value)
        return ModelDiscoveryResult((), 'fixture-time', connection_fingerprint(protocol, url, key))
    monkeypatch.setattr(current.model_discovery, 'discover', discover)
    payload = {'provider_id': 'test', 'provider': setup['data']['models']['providers']['test'], 'revision': revision}
    if source == 'setup':
        assert (await current.discover_models(payload)).models == ()
    else:
        with pytest.raises(ConfigurationError) as rejected:
            await current.discover_models(payload)
        assert rejected.value.status == 409


def test_busy_setup_applies_at_safe_boundary_without_changing_session_axes(client, isolated, provider):
    from test_integration import chat, detail, project, request, submit, wait
    gate = threading.Event()
    provider.plans['忙时首次设置'] = [Reply(text='完成设置前的请求', gate=gate)]
    project_id = project(client, isolated[2])
    identity = chat(client, project_id)
    submit(client, identity, '忙时首次设置')
    try:
        wait(client, identity, lambda _value: bool(provider.requests))
        before = request(client, 'GET', '/api/settings', params={'domain': 'setup'})
        before['data']['models']['default_model'] = 'test/two'
        before['data']['runtime']['work_phase'] = 'discuss'
        result = request(client, 'PATCH', '/api/settings', json={'domain': 'setup', 'revision': before['revision'], 'data': before['data']})
        assert identity in result['pending'] and result['snapshot']['state'] == 'ready'
        assert detail(client, identity)['pending_config']
    finally:
        gate.set()
    current = wait(client, identity, lambda value: value['status'] == 'completed' and not value['pending_config'])
    assert current['phase'] == 'execute'
    new = detail(client, chat(client, project_id))
    assert new['model_ref'] == 'test/two' and new['phase'] == 'discuss'


@pytest.mark.parametrize('key', ['   ', {'invalid': 'non-text-secret-never-exposed'}, None])
def test_public_provider_and_model_do_not_mark_invalid_keys_configured(isolated, key):
    raw = yaml.safe_load(config_path(isolated).read_text(encoding='utf-8'))
    raw['providers']['test']['api_key'] = key
    raw['providers']['test']['models']['one']['api_key'] = key
    write_config(isolated, raw)
    before = service(isolated).setup_snapshot()
    provider = before['data']['models']['providers']['test']
    assert provider['api_key_configured'] is False and provider['api_key'] == ''
    assert provider['models']['one']['api_key_configured'] is False
    assert provider['models']['one']['api_key'] == ''
    assert 'non-text-secret-never-exposed' not in json.dumps(before)


def test_unknown_nested_credentials_are_private_and_preserved_when_saving(isolated):
    raw = yaml.safe_load(config_path(isolated).read_text(encoding='utf-8'))
    secret = 'unknown-nested-secret-never-public'
    provider = raw['providers']['test']
    provider['custom_credentials'] = {'password': secret}
    model = provider['models']['one']
    model['custom_credentials'] = {'token': secret}
    model['metadata'] = {'id': 'fixture-one', 'source_fingerprint': 'f' * 64, 'fetched_at': '2026-10-13T00:00:00Z',
                         'password': secret, 'capabilities': {'custom_credentials': {'token': secret}}}
    raw['ui'] = {'custom_credentials': {'password': secret}}
    raw['runtime']['custom_credentials'] = {'token': secret}
    write_config(isolated, raw)
    current = service(isolated)
    before = current.setup_snapshot()
    assert before['state'] == 'ready'
    assert secret not in json.dumps(before) and secret not in json.dumps(current.snapshot())
    assert 'password' not in before['data']['models']['providers']['test']['models']['one']['metadata']
    before['data']['ui']['theme'] = 'light'
    before['data']['models']['providers']['test']['name'] = '改公开名称'
    result = current.save({'domain': 'setup', 'revision': before['revision'], 'data': before['data']})
    assert secret not in json.dumps(result)
    saved = yaml.safe_load(config_path(isolated).read_text(encoding='utf-8'))
    assert saved['providers']['test']['custom_credentials'] == {'password': secret}
    assert saved['providers']['test']['models']['one']['custom_credentials'] == {'token': secret}
    assert saved['providers']['test']['models']['one']['metadata']['password'] == secret
    assert saved['providers']['test']['models']['one']['metadata']['capabilities']['custom_credentials'] == {'token': secret}
    assert saved['ui']['custom_credentials'] == {'password': secret}
    assert saved['runtime']['custom_credentials'] == {'token': secret}


def test_invalid_metadata_is_an_empty_clearable_sentinel_without_raw_input(isolated):
    raw = yaml.safe_load(config_path(isolated).read_text(encoding='utf-8'))
    raw['providers']['test']['models']['one']['metadata'] = {'password': 'invalid-metadata-secret-never-public'}
    write_config(isolated, raw)
    current = service(isolated)
    before = current.setup_snapshot()
    assert before['state'] == 'repair'
    assert before['data']['models']['providers']['test']['models']['one']['metadata'] == {}
    assert 'invalid-metadata-secret-never-public' not in json.dumps(before)
    before['data']['models']['providers']['test']['models']['one']['metadata'] = None
    result = current.save({'domain': 'setup', 'revision': before['revision'], 'data': before['data']})
    assert result['snapshot']['state'] == 'ready'


def test_mcp_unknown_credentials_are_not_public_but_survive_a_known_field_edit(isolated):
    path = isolated[1] / '.lancher' / 'mcp.yaml'
    secret = 'unknown-mcp-server-secret-never-public'
    path.write_text(yaml.safe_dump({'mcp_servers': {'test': {'type': 'stdio', 'command': 'python',
                    'custom_credentials': {'token': secret}, 'env': {'TOKEN': 'masked-env-secret'}}}}), encoding='utf-8')
    current = service(isolated)
    before = current.snapshot()
    assert secret not in json.dumps(before) and 'masked-env-secret' not in json.dumps(before)
    before['global_mcp']['test']['tool_timeout_seconds'] = 90
    result = current.save({'domain': 'mcp', 'scope': 'global', 'revision': before['revision'], 'data': before['global_mcp']})
    assert secret not in json.dumps(result)
    saved = yaml.safe_load(path.read_text(encoding='utf-8'))['mcp_servers']['test']
    assert saved['custom_credentials'] == {'token': secret} and saved['env']['TOKEN'] == 'masked-env-secret'


@pytest.mark.parametrize('location', ['profile', 'resource', 'readiness'])
def test_unknown_execution_json_fields_are_unreadable_and_never_public(isolated, location):
    raw = yaml.safe_load(config_path(isolated).read_text(encoding='utf-8'))
    secret = 'unknown-execution-json-secret-never-public'
    profile = {'name': 'run', 'command_match': 'python', 'resources': [{'kind': 'external', 'key': 'gpu'}],
               'readiness': {'host': 'localhost', 'port': 8765}}
    target = profile if location == 'profile' else profile['resources'][0] if location == 'resource' else profile['readiness']
    target['custom_credentials'] = {'token': secret}
    raw['execution'] = {'command_profiles': [profile]}
    write_config(isolated, raw)
    current = service(isolated)
    setup = current.setup_snapshot()
    assert setup['state'] == 'unreadable' and setup['data'] is None
    assert secret not in json.dumps(setup) and secret not in json.dumps(current.snapshot())


def test_known_execution_json_structure_is_preserved_completely(isolated):
    raw = yaml.safe_load(config_path(isolated).read_text(encoding='utf-8'))
    profile = {'name': 'run', 'command_match': 'python', 'resources': [
                {'kind': 'external', 'key': 'gpu', 'mode': 'shared', 'recursive': False, 'lifetime': 'invocation'}],
               'readiness': {'kind': 'tcp', 'host': 'localhost', 'port': 8765, 'timeout_ms': 5000}}
    raw['execution'] = {'command_profiles': [profile]}
    write_config(isolated, raw)
    setup = service(isolated).setup_snapshot()
    assert setup['state'] == 'ready'
    assert setup['data']['execution']['command_profiles'] == [profile]


@pytest.mark.parametrize('level', ['provider', 'model'])
def test_claude_invalid_api_mode_keeps_a_safe_repair_control(isolated, level):
    raw = yaml.safe_load(config_path(isolated).read_text(encoding='utf-8'))
    raw['providers']['test']['protocol'] = 'claude'
    target = raw['providers']['test'] if level == 'provider' else raw['providers']['test']['models']['one']
    target['api_mode'] = None if level == 'provider' else {'password': 'invalid-api-mode-secret-never-public'}
    write_config(isolated, raw)
    current = service(isolated)
    before = current.setup_snapshot()
    assert before['state'] == 'repair'
    public = before['data']['models']['providers']['test']
    repaired = public if level == 'provider' else public['models']['one']
    assert 'api_mode' in repaired
    assert repaired['api_mode'] is None if level == 'provider' else repaired['api_mode'] == ''
    assert 'invalid-api-mode-secret-never-public' not in json.dumps(before)
    repaired['api_mode'] = 'auto' if level == 'provider' else None
    saved = current.save({'domain': 'setup', 'revision': before['revision'], 'data': before['data']})
    assert saved['snapshot']['state'] == 'ready'
