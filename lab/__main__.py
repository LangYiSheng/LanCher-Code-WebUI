"""独立启动入口，强制监听本机。"""
import argparse
from pathlib import Path

import uvicorn
from lancher_code.logging_system import configure_logging


def main():
    parser = argparse.ArgumentParser(description='LanCher Agent Lab 本地工作台')
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error('端口需要在 1024 到 65535 之间')
    root = Path(__file__).resolve().parent.parent
    configure_logging(log_path=root / 'data' / 'sdk-errors.log')
    uvicorn.run('lab.api:app', host='127.0.0.1', port=args.port, log_level='info')


if __name__ == '__main__':
    main()

