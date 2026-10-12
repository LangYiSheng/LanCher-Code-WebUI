"""共用配置适配的测试只使用显式传入的临时 home。"""
import copy
import json
from pathlib import Path

import pytest
import yaml

from webui.configuration import ConfigurationError, ConfigurationService


def test_public_configuration_redacts_and_preserves_existing_keys(isolated):
    root, home, project = isolated
    service = ConfigurationService(root, user_home=home)
    before = service.snapshot(project)
    assert 'fixture-secret-never-exposed' not in json.dumps(before)
    assert before['config']['providers']['test']['api_key'] == ''
    assert before['config']['providers']['test']['api_key_configured']
    models = {key: copy.deepcopy(before['config'][key]) for key in ('providers', 'default_model')}
    models['default_model'] = 'test/two'
    result = service.save({'domain': 'models', 'revision': before['revision'], 'data': models}, project)
    assert result['saved'] and result['revision'] != before['revision']
    source = yaml.safe_load((home / '.lancher' / 'lancher.yaml').read_text(encoding='utf-8'))
    assert source['providers']['test']['api_key'] == 'fixture-secret-never-exposed'
    assert source['default_model'] == 'test/two'


def test_stale_revision_and_invalid_data_preserve_shared_config(isolated):
    root, home, project = isolated
    service = ConfigurationService(root, user_home=home)
    before = service.snapshot(project)
    service.save({'domain': 'ui', 'revision': before['revision'], 'data': {'show_timestamps': True}}, project)
    valid = (home / '.lancher' / 'lancher.yaml').read_bytes()
    with pytest.raises(ConfigurationError) as rejected:
        service.save({'domain': 'ui', 'revision': before['revision'], 'data': {'show_timestamps': False}}, project)
    assert rejected.value.status == 409
    current = service.snapshot(project)
    with pytest.raises(ConfigurationError):
        service.save({'domain': 'ui', 'revision': current['revision'], 'data': {'show_timestamps': 'yes'}}, project)
    assert (home / '.lancher' / 'lancher.yaml').read_bytes() == valid


def test_project_mcp_scope_and_secret_roundtrip(isolated):
    root, home, project = isolated
    service = ConfigurationService(root, user_home=home)
    before = service.snapshot(project)
    servers = {'fixture': {'type': 'stdio', 'command': 'python', 'args': ['-V'], 'env': {'TOKEN': 'temporary-mcp-secret'}}}
    service.save({'domain': 'mcp', 'scope': 'project', 'revision': before['revision'], 'data': servers}, project)
    assert not (home / '.lancher' / 'mcp.yaml').exists()
    current = service.snapshot(project)
    assert 'temporary-mcp-secret' not in json.dumps(current)
    assert current['project_mcp']['fixture']['env']['TOKEN'] == ''
    service.save({'domain': 'mcp', 'scope': 'project', 'revision': current['revision'],
                  'data': current['project_mcp']}, project)
    saved = yaml.safe_load((project / '.lancher' / 'mcp.yaml').read_text(encoding='utf-8'))
    assert saved['mcp_servers']['fixture']['env']['TOKEN'] == 'temporary-mcp-secret'


def test_setting_scope_paths_are_all_in_fixture(isolated):
    root, home, project = isolated
    service = ConfigurationService(root, user_home=home)
    snapshot = service.snapshot(project)
    assert snapshot['configured']
    assert all(Path(path).is_relative_to(home) or Path(path).is_relative_to(project)
               for path in snapshot['paths'].values())



def test_real_sdk_rule_scope_and_model_overrides_preserved(isolated):
    from lancher_code.permissions.storage import PermissionStorage
    root, home, project = isolated
    path = home / '.lancher' / 'lancher.yaml'
    raw = yaml.safe_load(path.read_text(encoding='utf-8'))
    raw['providers']['test']['models']['one'].update(api_key='model-only-secret', base_url='https://model.invalid/v1')
    path.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding='utf-8')
    service = ConfigurationService(root, user_home=home)
    before = service.snapshot(project)
    public = {key: copy.deepcopy(before['config'][key]) for key in ('providers', 'default_model')}
    service.save({'domain': 'models', 'revision': before['revision'], 'data': public}, project)
    saved = yaml.safe_load(path.read_text(encoding='utf-8'))
    model = saved['providers']['test']['models']['one']
    assert model['api_key'] == 'model-only-secret' and model['base_url'] == 'https://model.invalid/v1'
    assert 'base_url' not in saved['providers']['test']['models']['two']
    current = service.snapshot(project)
    rules = [{'match': 'write_file:protected.txt', 'result': 'deny', 'match_kind': 'exact'}]
    service.save({'domain': 'rules', 'scope': 'project', 'revision': current['revision'], 'data': rules}, project)
    storage = PermissionStorage(project_rules_path=project / '.lancher' / 'permissions.yaml',
                                user_rules_path=home / '.lancher' / 'permissions.yaml')
    assert storage.rules_for_scope('project')[0].match == 'write_file:protected.txt'
    assert not (home / '.lancher' / 'permissions.yaml').exists()


def test_mcp_remove_env_and_headers_preserves_masked_secrets_and_templates(isolated):
    from lancher_code.mcp.config import load_mcp_config
    root, home, project = isolated
    config_path = home / '.lancher' / 'lancher.yaml'
    original_config = config_path.read_bytes()
    mcp_path = home / '.lancher' / 'mcp.yaml'
    raw = {'mcp_servers': {
        'stdio': {'type': 'stdio', 'command': 'python', 'args': ['-V'],
                  'env': {'REMOVE': 'deleted-env-secret', 'KEEP': 'preserved-env-secret',
                          'REF': '${MCP_FIXTURE_KEY}'}},
        'http': {'type': 'http', 'url': 'http://127.0.0.1:9/mcp',
                 'headers': {'X-Remove': 'deleted-header-secret', 'X-Keep': 'preserved-header-secret',
                             'X-Ref': '${MCP_FIXTURE_KEY}'}},
    }}
    mcp_path.write_text(yaml.safe_dump(raw), encoding='utf-8')
    service = ConfigurationService(root, user_home=home)
    before = service.snapshot(project)
    assert 'preserved-env-secret' not in json.dumps(before)
    edited = copy.deepcopy(before['global_mcp'])
    edited['stdio']['env'].pop('REMOVE')
    edited['stdio']['env_remove'] = ['REMOVE']
    edited['http']['headers'].pop('X-Remove')
    edited['http']['headers_remove'] = ['X-Remove']
    service.save({'domain': 'mcp', 'scope': 'global', 'revision': before['revision'], 'data': edited}, project)
    saved = yaml.safe_load(mcp_path.read_text(encoding='utf-8'))['mcp_servers']
    assert saved['stdio']['env'] == {'KEEP': 'preserved-env-secret', 'REF': '${MCP_FIXTURE_KEY}'}
    assert saved['http']['headers'] == {'X-Keep': 'preserved-header-secret', 'X-Ref': '${MCP_FIXTURE_KEY}'}
    assert 'env_remove' not in saved['stdio'] and 'headers_remove' not in saved['http']
    assert config_path.read_bytes() == original_config
    current = service.snapshot(project)
    assert set(current['global_mcp']['stdio']['env']) == {'KEEP', 'REF'}
    assert set(current['global_mcp']['http']['headers']) == {'X-Keep', 'X-Ref'}
    assert 'preserved-header-secret' not in json.dumps(current)
    configs, issues = load_mcp_config(project, home_dir=home, environ={'MCP_FIXTURE_KEY': 'expanded-test-value'})
    assert not issues
    actual = {server.name: server for server in configs}
    assert actual['stdio'].env_template['REF'] == '${MCP_FIXTURE_KEY}'
    assert actual['stdio'].env['REF'] == 'expanded-test-value'
    assert actual['http'].headers_template['X-Ref'] == '${MCP_FIXTURE_KEY}'
    assert actual['http'].headers['X-Ref'] == 'expanded-test-value'


def test_mcp_explicit_empty_timeouts_restore_defaults_but_omission_preserves_old_values(isolated):
    from lancher_code.mcp.config import validate_server_config
    root, home, project = isolated
    directory = project / '.lancher'
    directory.mkdir()
    path = directory / 'mcp.yaml'
    timeouts = {'startup_timeout_seconds': 2.5, 'tool_timeout_seconds': 17.5, 'close_timeout_seconds': 3.5}
    raw = {'mcp_servers': {name: {'type': 'stdio', 'command': 'python', 'args': [], **timeouts}
                          for name in ('restore', 'retained')}}
    path.write_text(yaml.safe_dump(raw), encoding='utf-8')
    service = ConfigurationService(root, user_home=home)
    before = service.snapshot(project)
    edited = copy.deepcopy(before['project_mcp'])
    for field in timeouts:
        edited['restore'][field] = None
        edited['retained'].pop(field)
    service.save({'domain': 'mcp', 'scope': 'project', 'revision': before['revision'], 'data': edited}, project)
    saved = yaml.safe_load(path.read_text(encoding='utf-8'))['mcp_servers']
    assert set(timeouts).isdisjoint(saved['restore'])
    assert {key: saved['retained'][key] for key in timeouts} == timeouts
    restored = validate_server_config('restore', saved['restore'])
    assert restored.startup_timeout_seconds is None and restored.close_timeout_seconds is None
    assert restored.tool_timeout_seconds == 60.0
    retained = validate_server_config('retained', saved['retained'])
    assert (retained.startup_timeout_seconds, retained.tool_timeout_seconds, retained.close_timeout_seconds) == (2.5, 17.5, 3.5)
    assert not (home / '.lancher' / 'mcp.yaml').exists()
