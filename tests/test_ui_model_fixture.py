"""验收模型列表必须显式启用，配置只能位于临时 fixture home。"""
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from fastapi.testclient import TestClient
import yaml


def test_model_api_fixture_is_opt_in_and_preserves_virtual_secret(isolated):
    from webui.api import create_app
    script_path = Path(__file__).resolve().parents[1] / 'scripts' / 'ui_acceptance_fixture.py'
    spec = spec_from_file_location('isolated_ui_acceptance_fixture', script_path)
    fixture_script = module_from_spec(spec)
    spec.loader.exec_module(fixture_script)
    fixture_script.PROJECT_ROOT = isolated[0]
    fixture_script.FIXTURE_ROOT = isolated[0] / 'data' / 'ui-acceptance'
    fixture, home = fixture_script.prepare()
    path = home / '.lancher' / 'lancher.yaml'
    before = path.read_bytes()
    app = create_app(root=fixture, user_home=home, enable_mcp=False)
    assert not any(getattr(route, 'path', '') == '/fixture-model-api/v1/models' for route in app.routes)
    fixture_script.prepare()
    assert path.read_bytes() == before
    original = yaml.safe_load(before)
    fixture_script.prepare(model_api=True, port=8899)
    changed = yaml.safe_load(path.read_text(encoding='utf-8'))
    assert changed['providers']['test']['base_url'] == 'http://127.0.0.1:8899/fixture-model-api/v1'
    assert changed['providers']['test']['api_mode'] == 'auto'
    assert changed['providers']['test']['api_key'] == original['providers']['test']['api_key']
    assert home.is_relative_to(isolated[0]) and path.is_relative_to(home)
    app = create_app(root=fixture, user_home=home, enable_mcp=False)
    fixture_script.add_fixture_model_api(app)
    with TestClient(app) as client:
        response = client.get('/fixture-model-api/v1/models')
        assert response.status_code == 200 and response.headers['content-type'].startswith('application/json')
        models = {row['id']: row for row in response.json()['data']}
        assert set(models) == {'fixture-one', 'fixture-two', 'discovered-mini', 'unknown'}
        assert models['fixture-two']['capabilities']['effort']['supported'] is False
        assert models['discovered-mini']['capabilities']['effort']['supported_levels'] == ['low', 'ultra']
        assert 'capabilities' not in models['unknown']
