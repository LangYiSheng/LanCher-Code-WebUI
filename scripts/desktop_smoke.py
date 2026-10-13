"""真实桌面验收入口；与冻结 EXE 共用同一个验收过程。"""
from pathlib import Path
from desktop.__main__ import run
from desktop.acceptance import smoke

if __name__=='__main__':
    root=Path(__file__).resolve().parent.parent
    run(root/'data/desktop-build/resources',root/'data/desktop-build/source-smoke',smoke=smoke)
