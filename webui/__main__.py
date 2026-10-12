"""本机单 worker 启动入口，负责收到退出操作后的服务器收尾。"""
import argparse
import asyncio
from pathlib import Path
import uvicorn
from lancher_code.logging_system import configure_logging
from .api import create_app


def main():
    parser=argparse.ArgumentParser(description='LanCher Code WebUI 本地工作台')
    parser.add_argument('--port',type=int,default=8765)
    args=parser.parse_args()
    if not 1024<=args.port<=65535:parser.error('端口须在1024至65535之间')
    root=Path(__file__).resolve().parent.parent
    configure_logging(log_path=root/'data/sdk-errors.log')
    app=create_app(root)
    server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=args.port,workers=1,log_level='info'))
    def stop():server.should_exit=True
    app.state.shutdown_callback=stop
    asyncio.run(server.serve())

if __name__=='__main__':main()
