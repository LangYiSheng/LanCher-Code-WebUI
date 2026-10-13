# -*- mode: python ; coding: utf-8 -*-
# 构建只读取已固定 SDK 和共享前端，不收集用户配置、数据库或原仓库。
from pathlib import Path
from PyInstaller.utils.hooks import collect_all
root=Path(SPECPATH).parent
hidden=[]
datas=[(str(root/'data/desktop-build/frontend-dist'),'frontend/dist'),(str(root/'vendor/snapshot.json'),'vendor')]
binaries=[]
for package in ['webview','lancher_code','mcp','tree_sitter','tree_sitter_bash','clr_loader']:
    package_data,package_binaries,package_hidden=collect_all(package,filter_submodules=lambda name:not name.startswith(("webview.platforms.android","mcp.cli","lancher_code.tui","lancher_code.cli")))
    datas+=package_data;binaries+=package_binaries;hidden+=package_hidden
hidden+=['uvicorn.logging','uvicorn.loops.asyncio','uvicorn.protocols.http.h11_impl','uvicorn.lifespan.on']
a=Analysis([str(root/'desktop_entry.py')],pathex=[str(root)],binaries=binaries,datas=datas,hiddenimports=hidden,
    excludes=['lancher_code.tui','tkinter','PyQt5','PyQt6','PySide2','PySide6'],noarchive=False)
pyz=PYZ(a.pure)
exe=EXE(pyz,a.scripts,[],exclude_binaries=True,name='LanCher Code Desktop',debug=False,bootloader_ignore_signals=False,
    strip=False,upx=False,console=False,icon=str(root/'data/desktop-build/frontend-dist/favicon.ico'))
coll=COLLECT(exe,a.binaries,a.datas,strip=False,upx=False,name='LanCher Code Desktop')
