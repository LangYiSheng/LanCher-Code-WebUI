"""用户主动触发的本机目录选择器；导入模块不会弹窗。"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
import subprocess
import sys


async def pick_directory() -> dict:
    if sys.platform != "win32":
        return {"path": None, "cancelled": True, "error": "当前系统请直接填写本机项目目录。"}
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-B", str(Path(__file__).resolve()), "--choose",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    try:
        stdout, _stderr = await asyncio.wait_for(process.communicate(), timeout=300)
    except asyncio.CancelledError:
        process.kill()
        await process.wait()
        raise
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()
        return {"path": None, "cancelled": True, "error": "目录选择器已超时，请重新打开。"}
    if process.returncode:
        return {"path": None, "cancelled": True, "error": "系统目录选择器无法打开，请直接填写项目目录。"}
    try:
        result = json.loads(stdout.decode("ascii"))
        if not isinstance(result, dict):
            raise ValueError("invalid result")
        selected = result.get("path")
        if not selected:
            return {"path": None, "cancelled": True}
        path = Path(selected).resolve()
        if not path.is_dir():
            raise ValueError("not directory")
        return {"path": str(path), "cancelled": False}
    except (UnicodeError, ValueError, TypeError, OSError):
        return {"path": None, "cancelled": True, "error": "目录选择结果无效，请直接填写项目目录。"}


def _choose() -> None:
    import tkinter as tk
    from tkinter import filedialog
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        selected = filedialog.askdirectory(title="选择 LanCher Code 项目目录", mustexist=True, parent=root)
        print(json.dumps({"path": selected or None, "cancelled": not bool(selected)}, ensure_ascii=True), flush=True)
    finally:
        root.destroy()


if __name__ == "__main__":
    if sys.argv[1:] != ["--choose"]:
        raise SystemExit(2)
    _choose()
