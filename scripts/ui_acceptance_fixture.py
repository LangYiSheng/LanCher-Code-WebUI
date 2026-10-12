"""独立 UI 验收服务；只使用 fixture home、工程和数据库。"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import sys
from datetime import datetime, timezone

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = PROJECT_ROOT / 'data' / 'ui-acceptance'


def prepare(sync_dist: bool = False) -> tuple[Path, Path]:
    fixture = FIXTURE_ROOT.resolve()
    expected_parent = (PROJECT_ROOT / 'data').resolve()
    if fixture.parent != expected_parent or FIXTURE_ROOT.is_symlink():
        raise RuntimeError('UI 验收路径必须位于本项目 data 下且不是链接。')
    fixture.mkdir(parents=True, exist_ok=True)
    (fixture / 'vendor').mkdir(exist_ok=True)
    shutil.copy2(PROJECT_ROOT / 'vendor' / 'snapshot.json', fixture / 'vendor' / 'snapshot.json')
    home = fixture / 'fixture-home'
    config_dir = home / '.lancher'
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / 'lancher.yaml'
    if not config_path.exists():
        config_path.write_text('''providers:
  test:
    name: UI 验收虚拟供应商
    protocol: openai
    base_url: http://127.0.0.1:1/v1
    api_key: fixture-api-key-only
    models:
      one:
        model_name: fixture-one
      two:
        model_name: fixture-two
default_model: test/one
runtime:
  execution_access: project
''', encoding='utf-8')
    for name in ('project-a', 'project-b'):
        (fixture / name).mkdir(exist_ok=True)
    dist = fixture / 'frontend' / 'dist'
    dist.mkdir(parents=True, exist_ok=True)
    if sync_dist:
        source = PROJECT_ROOT / 'frontend' / 'dist'
        if not (source / 'index.html').is_file():
            raise RuntimeError('前端 dist 还未构建。')
        shutil.copytree(source, dist, dirs_exist_ok=True)
    elif not (dist / 'index.html').exists():
        (dist / 'index.html').write_text('<!doctype html><title>UI acceptance fixture pending build</title>', encoding='utf-8')
    (fixture / 'fixture.json').write_text(json.dumps({
        'root': str(fixture), 'user_home': str(home), 'enable_mcp': False,
        'projects': [str(fixture / name) for name in ('project-a', 'project-b')],
    }, ensure_ascii=False, indent=2), encoding='utf-8')
    return fixture, home


def main() -> None:
    parser = argparse.ArgumentParser(description='只操作独立虚拟配置的 UI 验收实例')
    parser.add_argument('--port', type=int, default=8767)
    parser.add_argument('--prepare-only', action='store_true')
    parser.add_argument('--sync-dist', action='store_true')
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error('端口须在 1024 至 65535 之间。')
    fixture, home = prepare(args.sync_dist)
    if args.prepare_only:
        print(json.dumps({'prepared': True, 'root': str(fixture), 'user_home': str(home)}, ensure_ascii=False))
        return
    sys.path.insert(0, str(PROJECT_ROOT))
    import uvicorn
    from lancher_code.logging_system import configure_logging
    from webui.api import create_app
    data = fixture / 'data'
    data.mkdir(exist_ok=True)
    configure_logging(log_path=data / 'sdk-errors.log')
    app = create_app(root=fixture, user_home=home, enable_mcp=False)
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=args.port, workers=1, log_level='info'))
    app.state.shutdown_callback = lambda: setattr(server, 'should_exit', True)
    (fixture / 'server.pid.json').write_text(json.dumps({
        'process_id': os.getpid(), 'port': args.port, 'project_root': str(PROJECT_ROOT),
        'fixture_root': str(fixture), 'python': sys.executable,
        'started_utc': datetime.now(timezone.utc).isoformat(),
    }, indent=2), encoding='utf-8')
    server.run()


if __name__ == '__main__':
    main()
