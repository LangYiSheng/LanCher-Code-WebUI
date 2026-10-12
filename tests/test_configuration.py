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
