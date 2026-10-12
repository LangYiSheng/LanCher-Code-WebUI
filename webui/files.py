"""项目文件浏览与引用校验；不会跟随项目外路径。"""
from __future__ import annotations

import difflib
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import stat

MAX_FILES = 3000
MAX_PREVIEW_BYTES = 1024 * 1024
MAX_DIFF_BYTES = 1024 * 1024
_SKIPPED = {".git", ".lancher", ".venv", "node_modules", "__pycache__", ".cache"}
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
             *(f"LPT{i}" for i in range(1, 10))}


class FilesError(ValueError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def resolve_project_file(project_root: Path, raw_path: str) -> Path:
    if not isinstance(raw_path, str) or not raw_path or raw_path != raw_path.strip():
        raise FilesError("文件引用必须是项目内相对路径。", 403)
    normalized = raw_path.replace("\\", "/")
    windows = PureWindowsPath(raw_path)
    parts = normalized.split("/")
    if (windows.drive or windows.root or PurePosixPath(normalized).is_absolute()
            or len(normalized) > 4096 or any(char in normalized for char in '\x00:<>|?*"')
            or any(ord(char) < 32 for char in normalized)
            or any(part in {"", ".", ".."} or part.endswith((" ", ".")) for part in parts)
            or any(part.split(".")[0].upper() in _RESERVED for part in parts)
            or parts[0] in {".git", ".lancher"}):
        raise FilesError("文件引用越界或包含不支持的路径。", 403)
    root = Path(project_root).resolve()
    candidate = root.joinpath(*parts)
    resolved = candidate.resolve()
    if (not resolved.is_relative_to(root) or resolved == root
            or resolved.relative_to(root).parts[0] in {".git", ".lancher"}):
        raise FilesError("文件引用不能指向项目目录外部。", 403)
    try:
        info = resolved.stat()
        if stat.S_ISREG(info.st_mode) and info.st_nlink > 1:
            raise FilesError("预览文件存在硬链接，不能确认它只属于当前项目。", 403)
    except FileNotFoundError:
        pass
    return resolved


def validate_reference(project_root: Path, path: str) -> str:
    target = resolve_project_file(project_root, path)
    if not target.is_file():
        raise FilesError("引用文件不存在。", 404)
    return target.relative_to(Path(project_root).resolve()).as_posix()


def list_files(project_root: Path, q: str = "") -> dict:
    root = Path(project_root).resolve()
    if not root.is_dir():
        raise FilesError("项目目录不存在。", 404)
    if not isinstance(q, str) or len(q) > 300:
        raise FilesError("文件检索词无效。")
    query = q.casefold()
    rows = []
    truncated = False
    visited = 0
    for directory, dirs, names in os.walk(root, followlinks=False):
        dirs[:] = sorted(name for name in dirs if name not in _SKIPPED
                         and not (Path(directory) / name).is_symlink()
                         and not getattr(Path(directory) / name, "is_junction", lambda: False)())
        for name in sorted(names):
            visited += 1
            if visited > 30000:
                truncated = True
                break
            path = Path(directory) / name
            relative = path.relative_to(root).as_posix()
            if query and query not in relative.casefold():
                continue
            try:
                target = resolve_project_file(root, relative)
                if not target.is_file():
                    continue
                rows.append({"path": relative, "size": target.stat().st_size})
            except (FilesError, OSError):
                continue
            if len(rows) >= MAX_FILES:
                truncated = True
                break
        if truncated:
            break
    return {"files": sorted(rows, key=lambda item: item["path"]), "truncated": truncated, "query": q}


def file_change(project_root: Path, path: str, before: str | None) -> dict:
    """按本对话首次操作前的文本基线判断净变化，恢复原样不算变更。"""
    root = Path(project_root).resolve()
    target = resolve_project_file(root, path)
    relative = target.relative_to(root).as_posix()
    if not target.exists():
        return {"path": relative, "size": 0,
                "status": "unchanged" if before is None else "deleted"}
    if not target.is_file():
        raise FilesError("目标已变成目录，无法作为文件变更展示。", 409)
    size = target.stat().st_size
    if before is None:
        status = "added"
    elif size > MAX_PREVIEW_BYTES:
        # 已有基线的原文件不超过此上限；现在超限说明它已变化。
        status = "modified"
    else:
        try:
            status = "unchanged" if target.read_text(encoding="utf-8-sig") == before else "modified"
        except UnicodeError:
            status = "modified"
    return {"path": relative, "size": size, "status": status}


def read_file(project_root: Path, path: str, baseline=None) -> dict:
    root = Path(project_root).resolve()
    target = resolve_project_file(root, path)
    relative = target.relative_to(root).as_posix()
    recorded = isinstance(baseline, dict) and relative in baseline
    removed = not target.exists() and recorded and baseline[relative] is not None
    if not target.is_file() and not removed:
        raise FilesError("文件不存在。", 404)
    if not removed and target.stat().st_size > MAX_PREVIEW_BYTES:
        raise FilesError("文件超过 1 MiB 预览上限。", 413)
    try:
        content = "" if removed else target.read_text(encoding="utf-8-sig")
    except UnicodeError as exc:
        raise FilesError("这个文件无法作为 UTF-8 文本预览。", 415) from exc
    except OSError as exc:
        raise FilesError("文件无法读取。", 403) from exc
    if recorded or isinstance(baseline, str):
        before = baseline[relative] if recorded else baseline
        status = file_change(root, relative, before)["status"]
        old = before or ""
        # 无末尾换行时也独立呈现增删行，避免 '-old+new' 粘成一行。
        lines = difflib.unified_diff(
            old.splitlines(keepends=True), content.splitlines(keepends=True),
            fromfile=f"a/{relative}" if before is not None else "/dev/null",
            tofile="/dev/null" if removed else f"b/{relative}",
        )
        diff = "".join(line if line.endswith("\n") else line + "\n\\ No newline at end of file\n"
                       for line in lines)
        return {"path": relative, "content": content, "diff": diff[:MAX_DIFF_BYTES],
                "diff_source": "baseline", "diff_truncated": len(diff) > MAX_DIFF_BYTES,
                "change_status": status, "deleted": removed}
    # 项目源码与本对话变更是两种视图；不把整个 Git 工作区变化归给当前对话。
    return {"path": relative, "content": content, "diff": "", "diff_source": "none",
            "diff_truncated": False, "change_status": "unchanged", "deleted": False}
