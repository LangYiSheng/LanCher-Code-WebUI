"""移除旧实验历史接口，只保留备份和原生 SDK 历史。"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient


def test_retired_legacy_routes_and_bootstrap_never_read_or_remove_backup(isolated, provider, monkeypatch):
    from webui.api import create_app
    from webui.manager import AppManager

    root, home, workspace = isolated
    backup_root = root / 'data' / 'legacy'
    legacy_meta = backup_root / 'data' / 'sessions' / 'old-fixture' / 'meta.json'
    legacy_meta.parent.mkdir(parents=True)
    legacy_meta.write_text(json.dumps({'title': '旧实验记录备份', 'messages': [
        {'role': 'user', 'content': 'fixture-private-legacy-content'}]}, ensure_ascii=False), encoding='utf-8')
    old_lab_file = root.parent / 'old-lab' / 'keep.txt'
    old_lab_file.parent.mkdir()
    old_lab_file.write_bytes(b'old-lab-fixture-preserved')
    snapshot_path = root / 'vendor' / 'snapshot.json'
    snapshot = json.loads(snapshot_path.read_text(encoding='utf-8'))
    snapshot['legacy_source'] = str(old_lab_file.parent)
    snapshot_path.write_text(json.dumps(snapshot), encoding='utf-8')
    watched = [legacy_meta, old_lab_file, snapshot_path, home / '.lancher' / 'lancher.yaml']
    before = {path: path.read_bytes() for path in watched}

    assert not hasattr(AppManager, 'legacy')
    with monkeypatch.context() as guards:
        for name in ('read_text', 'read_bytes', 'iterdir'):
            original = getattr(Path, name)

            def read_without_legacy(path, *args, _operation=original, **kwargs):
                assert not path.resolve().is_relative_to(backup_root.resolve()), 'API 不应再访问旧实验历史备份。'
                return _operation(path, *args, **kwargs)

            guards.setattr(Path, name, read_without_legacy)
        app = create_app(root=root, user_home=home, provider_factory=lambda _: provider, enable_mcp=False)
        with TestClient(app, raise_server_exceptions=False) as client:
            assert client.get('/api/legacy').status_code == 404
            assert client.get('/api/legacy/old-fixture').status_code == 404
            bootstrap = client.get('/api/bootstrap')
            assert bootstrap.status_code == 200, bootstrap.text
            assert 'legacy_count' not in bootstrap.json()
            assert 'fixture-private-legacy-content' not in bootstrap.text
            paths = client.get('/openapi.json').json()['paths']
            assert not any(path.startswith('/api/legacy') for path in paths)
            assert '/api/legacy' not in client.get('/docs').text

    assert {path: path.read_bytes() for path in watched} == before
    assert backup_root.is_dir() and old_lab_file.parent.is_dir()
