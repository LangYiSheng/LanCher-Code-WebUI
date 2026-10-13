"""首次设置专用验收宿主；配置和工程始终位于忽略的 data 目录。"""
from __future__ import annotations

import argparse
import re
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8872)
    parser.add_argument('--scenario', choices=('new', 'discovery', 'repair', 'unreadable', 'welcome', 'missing'), default='new')
    parser.add_argument('--run-id', default='', help='使用另一组专用目录，不重置已有验收数据')
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error('端口须在 1024 至 65535 之间。')
    if args.run_id and not re.fullmatch(r'[a-z0-9-]{1,50}', args.run_id):
        parser.error('验收分组只能包含小写字母、数字和短横线。')
    parent = ROOT / 'data' / 'ui-setup-acceptance'
    if args.run_id:
        if parent.is_symlink():
            raise RuntimeError('验收目录不能是链接。')
        parent = parent / args.run_id
        parent.mkdir(parents=True, exist_ok=True)
    fixture = parent / args.scenario
    if parent.is_symlink() or fixture.is_symlink() or fixture.resolve().parent != parent.resolve():
        raise RuntimeError('验收目录必须位于本项目 data/ui-setup-acceptance 下。')
    fixture.mkdir(parents=True, exist_ok=True)
    (fixture / 'vendor').mkdir(exist_ok=True)
    shutil.copy2(ROOT / 'vendor' / 'snapshot.json', fixture / 'vendor' / 'snapshot.json')
    dist = ROOT / 'frontend' / 'dist'
    shutil.copytree(dist, fixture / 'frontend' / 'dist', dirs_exist_ok=True)
    home = fixture / 'fixture-home'
    config_dir = home / '.lancher'
    config_dir.mkdir(parents=True, exist_ok=True)
    path = config_dir / 'lancher.yaml'
    if not path.exists() and args.scenario == 'repair':
        path.write_text(f'''providers:
  fixture:
    name: 待修复的供应商
    protocol: openai
    base_url: http://127.0.0.1:{args.port}/fixture-model-api/v1
    api_key: fixture-secret-preserved
    models:
      one:
        model_name: fixture-one
default_model: fixture/missing
runtime:
  work_phase: invalid
execution:
  limits:
    max_processes: 0
''', encoding='utf-8')
    elif not path.exists() and args.scenario == 'unreadable':
        path.write_text('providers: [broken\n', encoding='utf-8')
    elif not path.exists() and args.scenario == 'missing':
        path.write_text(f'''providers:
  fixture:
    name: 已有供应商
    protocol: openai
    base_url: http://127.0.0.1:{args.port}/fixture-model-api/v1
    api_key: fixture-key-only
    models: {{}}
''', encoding='utf-8')
    (fixture / 'project').mkdir(exist_ok=True)
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / 'scripts'))
    import uvicorn
    from webui.api import create_app
    from ui_acceptance_fixture import add_fixture_model_api
    app = create_app(root=fixture, user_home=home, enable_mcp=False)
    add_fixture_model_api(app)
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=args.port, log_level='warning'))
    app.state.shutdown_callback = lambda: setattr(server, 'should_exit', True)
    server.run()


if __name__ == '__main__':
    main()
