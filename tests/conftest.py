"""所有配置、文件和命令都落入 pytest 临时目录。"""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from provider_helpers import ScriptedProvider


@pytest.fixture
def isolated(tmp_path):
    root = tmp_path / 'webui'
    (root / 'vendor').mkdir(parents=True)
    (root / 'vendor' / 'snapshot.json').write_text(json.dumps({'commit': '00e0797-fixture'}), encoding='utf-8')
    (root / 'frontend' / 'dist').mkdir(parents=True)
    (root / 'frontend' / 'dist' / 'index.html').write_text('<!doctype html><title>fixture</title>', encoding='utf-8')
    home = tmp_path / 'home'
    (home / '.lancher').mkdir(parents=True)
    (home / '.lancher' / 'lancher.yaml').write_text('''providers:
  test:
    name: 测试
    protocol: openai
    base_url: http://127.0.0.1:1/v1
    api_key: fixture-secret-never-exposed
    models:
      one:
        model_name: fixture-one
      two:
        model_name: fixture-two
default_model: test/one
runtime:
  execution_access: project
''', encoding='utf-8')
    project = tmp_path / 'project'
    project.mkdir()
    return root, home, project


@pytest.fixture
def provider():
    return ScriptedProvider()


@pytest.fixture
def client(isolated, provider):
    from webui.api import create_app
    root, home, _project = isolated
    with TestClient(create_app(root=root, user_home=home, provider_factory=lambda _config: provider,
                               enable_mcp=False), raise_server_exceptions=False) as current:
        yield current
