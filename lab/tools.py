"""实验工具：路径严格限制，生成代码只在 Docker 临时快照里执行。"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import tempfile
from typing import Callable
from uuid import uuid4

from lancher_code.contracts.tools import ToolDefinition, ToolPermissionMetadata, ToolExecutionResult
from lancher_code.tools.builtin.read_file import ReadFileTool
from lancher_code.tools.builtin.write_file import WriteFileTool
from lancher_code.tools.core.base import build_tool_error, build_tool_success
from lancher_code.tools.core.registry import ToolRegistry

MAX_FILE_BYTES = 512 * 1024
MAX_PROJECT_BYTES = 4 * 1024 * 1024
MAX_FILES = 256
MAX_OUTPUT_BYTES = 64 * 1024
IMAGE = "python:3.14-slim"
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
             *(f"LPT{i}" for i in range(1, 10))}


def _check_node(path: Path) -> None:
    """拒绝所有链接、重解析点与多硬链接文件。"""
    try:
        info = path.lstat()
    except FileNotFoundError:
        return
    if (stat.S_ISLNK(info.st_mode)
            or getattr(info, "st_file_attributes", 0) & 0x400
            or (stat.S_ISREG(info.st_mode) and info.st_nlink > 1)):
        raise ValueError("实验路径不能包含符号链接、junction 或硬链接。")


def validate_lab_directory(directory: Path) -> Path:
    """从驱动器到目录逐级检查，拒绝祖先 junction 或符号链接重定向。"""
    directory = Path(directory).absolute()
    for ancestor in reversed(directory.parents):
        _check_node(ancestor)
    _check_node(directory)
    return directory.resolve()


def resolve_lab_path(workspace: Path, raw_path: str) -> Path:
    """文件 API 与工具共用的严格相对路径入口。"""
    if not isinstance(raw_path, str) or not raw_path or raw_path != raw_path.strip():
        raise ValueError("path 必须为非空相对路径。")
    if any(char in raw_path for char in '\\:\x00<>|?*"') or any(ord(char) < 32 for char in raw_path):
        raise ValueError("实验路径只支持使用 / 的普通相对路径。")
    parts = raw_path.split("/")
    if (PurePosixPath(raw_path).is_absolute() or len(raw_path) > 240
            or any(not part or part in {".", ".."} or part.startswith(".")
                   or part.endswith((" ", ".")) for part in parts)
            or any(part.split(".")[0].upper() in _RESERVED for part in parts)):
        raise ValueError("实验路径不能越界、使用隐藏目录或 Windows 保留名称。")
    root = validate_lab_directory(workspace)
    resolved_root = root.resolve()
    candidate = root
    for part in parts:
        candidate = candidate / part
        _check_node(candidate)
    resolved = candidate.resolve()
    if not resolved.is_relative_to(resolved_root) or resolved == resolved_root:
        raise ValueError("实验路径不能指向工作区外部。")
    return resolved


def list_workspace_files(workspace: Path) -> list[str]:
    """只列出安全的可见普通文件；不穿越链接或 SDK 元数据目录。"""
    root = validate_lab_directory(workspace)
    files: list[str] = []

    def visit(directory: Path) -> None:
        with os.scandir(directory) as entries:
            for entry in sorted(entries, key=lambda value: value.name.casefold()):
                if entry.name.startswith("."):
                    continue
                path = Path(entry.path)
                _check_node(path)
                if entry.is_dir(follow_symlinks=False):
                    visit(path)
                elif entry.is_file(follow_symlinks=False):
                    relative = path.relative_to(root).as_posix()
                    resolve_lab_path(root, relative)
                    if path.stat().st_size > MAX_FILE_BYTES:
                        raise ValueError("实验文件超过 512 KiB。")
                    files.append(relative)
                    if len(files) > MAX_FILES:
                        raise ValueError("实验项目最多支持 256 个文件。")
                else:
                    raise ValueError("实验项目包含不支持的特殊文件。")

    visit(root)
    return files


class ConfinedReadFile:
    def __init__(self, workspace: Path):
        self.workspace = workspace
        self.native = ReadFileTool()

    @property
    def definition(self):
        return ToolDefinition(
            name="read_file", description="完整读取实验项目的可见文本文件，path 只支持相对路径。",
            category="read", allowed_phases=("discuss", "plan", "execute"),
            input_schema={"type": "object", "properties": {
                "path": {"type": "string"}, "offset": {"type": "integer", "minimum": 0},
                "limit": {"type": "integer", "minimum": 1, "maximum": 400}},
                "required": ["path"], "additionalProperties": False},
        )

    async def execute(self, arguments, context):
        try:
            path = resolve_lab_path(self.workspace, arguments.get("path"))
            if path.is_file() and path.stat().st_size > MAX_FILE_BYTES:
                raise ValueError("实验文件超过 512 KiB。")
            prepared = dict(arguments)
            prepared["path"] = path.relative_to(self.workspace).as_posix()
            return await self.native.execute(prepared, context)
        except (ValueError, OSError) as error:
            return build_tool_error(summary="实验读取被拒绝", error_code="lab_path_denied",
                                    error_message=str(error), tool_name="read_file")


class ConfinedWriteFile:
    def __init__(self, workspace: Path):
        self.workspace = workspace
        self.native = WriteFileTool()

    @property
    def definition(self):
        return ToolDefinition(
            name="write_file",
            description="写入实验项目可见文本文件；已有文件须先完整 read_file。path 只能为相对路径。",
            category="write",
            input_schema={"type": "object",
                          "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                          "required": ["path", "content"], "additionalProperties": False},
        )

    async def execute(self, arguments, context):
        try:
            path = resolve_lab_path(self.workspace, arguments.get("path"))
            content = arguments.get("content")
            if not isinstance(content, str) or len(content.encode("utf-8")) > MAX_FILE_BYTES:
                raise ValueError("content 必须是最多 512 KiB 的 UTF-8 文本。")
            # 原生写工具继续提供原子写入与读取版本防护。
            return await self.native.execute(
                {"path": path.relative_to(self.workspace).as_posix(), "content": content}, context)
        except (ValueError, OSError) as error:
            return build_tool_error(summary="实验写入被拒绝", error_code="lab_path_denied",
                                    error_message=str(error), tool_name="write_file")


class LabList:
    def __init__(self, workspace: Path):
        self.workspace = workspace

    @property
    def definition(self):
        return ToolDefinition(
            name="lab_list", description="列出实验项目的可见文件；不显示 SDK 内部记录。",
            category="read", allowed_phases=("discuss", "plan", "execute"),
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        )

    async def execute(self, arguments, context):
        try:
            files = list_workspace_files(self.workspace)
            return build_tool_success(content=json.dumps({"files": files}, ensure_ascii=False),
                                      summary=f"{len(files)} 个实验文件", tool_name="lab_list")
        except (ValueError, OSError) as error:
            return build_tool_error(summary="列出实验文件失败", error_code="lab_path_denied",
                                    error_message=str(error), tool_name="lab_list")


class RunTests:
    timeout_seconds = 65.0

    def __init__(self, workspace: Path, docker_available: bool, on_log: Callable[[str], None]):
        self.workspace, self.docker_available, self.on_log = workspace, docker_available, on_log

    @property
    def definition(self):
        return ToolDefinition(
            name="run_tests",
            description="批准后，在无网络 Docker 只读项目快照中执行固定 unittest 命令。测试临时数据须使用 tempfile 或 /tmp（32 MiB），不能改写项目源码；不会在宿主机执行生成代码。",
            category="command",
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
            permission=ToolPermissionMetadata(
                source="external", rule_key="run_tests", display_name="隔离运行实验测试",
                server_name="agent-lab", remote_tool_name="run_tests",
            ),
        )

    async def execute(self, arguments, context):
        docker = shutil.which("docker") if self.docker_available else None
        if docker is None:
            return self._result("isolation_unavailable", "Docker 不可用；生成代码未在宿主机执行。")
        container = "lancher-lab-" + uuid4().hex
        process = None
        sandbox_root = validate_lab_directory(self.workspace.parent / ".sandbox")
        sandbox_root.mkdir(exist_ok=True)
        validate_lab_directory(sandbox_root)
        snapshot = tempfile.TemporaryDirectory(prefix="run-", dir=sandbox_root, delete=False)
        if not Path(snapshot.name).resolve().is_relative_to(sandbox_root.resolve()):
            raise ValueError("临时测试快照未落在指定隔离目录内。")
        cancelled = False
        result = None
        cleanup_error = None
        try:
            root = Path(snapshot.name)
            total = 0
            for relative in list_workspace_files(self.workspace):
                source = resolve_lab_path(self.workspace, relative)
                data = source.read_bytes()
                total += len(data)
                if len(data) > MAX_FILE_BYTES or total > MAX_PROJECT_BYTES:
                    raise ValueError("实验快照超过文件大小或 4 MiB 总量限制。")
                destination = root / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(data)
            self.on_log("$ python -m unittest discover -s tests -v")
            command = [
                docker, "run", "--rm", "--name", container, "--network", "none", "--log-driver", "none",
                "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
                "--memory", "256m", "--cpus", "1", "--pids-limit", "64",
                "--tmpfs", "/tmp:rw,noexec,nosuid,size=32m",
                "--mount", f"type=bind,source={root},target=/workspace,readonly",
                "--workdir", "/workspace", "--env", "PYTHONDONTWRITEBYTECODE=1",
                IMAGE, "python", "-m", "unittest", "discover", "-s", "tests", "-v",
            ]
            process = await asyncio.create_subprocess_exec(
                *command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
            captured = bytearray()

            async def consume():
                while True:
                    chunk = await process.stdout.read(4096)
                    if not chunk:
                        break
                    room = MAX_OUTPUT_BYTES - len(captured)
                    if room > 0:
                        kept = chunk[:room]
                        captured.extend(kept)
                        self.on_log(kept.decode("utf-8", errors="replace"))
                return await process.wait()

            try:
                exit_code = await asyncio.wait_for(consume(), timeout=45)
            except asyncio.TimeoutError:
                result = self._result("tests_timeout", "隔离测试超过 45 秒，容器已安排清理。",
                                      output=captured.decode("utf-8", errors="replace"))
            else:
                output = captured.decode("utf-8", errors="replace")
                result = self._result(None if exit_code == 0 else "tests_failed",
                                      "隔离测试通过。" if exit_code == 0 else "隔离测试失败。",
                                      exit_code=exit_code, output=output)
        except asyncio.CancelledError:
            cancelled = True
            raise
        except (ValueError, OSError) as error:
            result = self._result("sandbox_error", str(error))
        finally:
            # 先终止容器，再删除临时快照；取消也必须完成此收尾。
            cleanup = asyncio.create_task(self._cleanup(docker, container, process, snapshot))
            interrupted = False
            while not cleanup.done():
                try:
                    await asyncio.shield(cleanup)
                except asyncio.CancelledError:
                    interrupted = True
            cleanup_error = cleanup.result()
            if cleanup_error:
                self.on_log("容器清理未确认，已保留临时快照：" + cleanup_error)
            if interrupted or cancelled:
                raise asyncio.CancelledError
        if cleanup_error:
            return self._result("sandbox_cleanup_failed", cleanup_error)
        if result is None:
            raise RuntimeError("隔离测试结束但没有执行结果。")
        return result

    async def _cleanup(self, docker, container, process, snapshot):
        """清理之后查询容器列表，不能把客户端退出当成容器已停止。"""
        confirmed_absent = False
        error = None
        removal = probe = None
        try:
            removal = await asyncio.create_subprocess_exec(
                docker, "rm", "-f", container,
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
            try:
                await asyncio.wait_for(removal.wait(), timeout=8)
            except asyncio.TimeoutError:
                removal.kill()
                await removal.wait()
            probe = await asyncio.create_subprocess_exec(
                docker, "ps", "-aq", "--filter", f"name=^/{container}$",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            try:
                stdout, stderr = await asyncio.wait_for(probe.communicate(), timeout=6)
            except asyncio.TimeoutError:
                probe.kill()
                await probe.wait()
                raise RuntimeError("Docker 容器状态查询超时，无法确认清理完成。")
            if probe.returncode != 0:
                detail = stderr.decode("utf-8", errors="replace")[:400]
                raise RuntimeError("Docker 无法确认容器清理状态：" + detail)
            if stdout.strip():
                raise RuntimeError("Docker 返回容器仍存在，未删除其挂载的临时快照。")
            confirmed_absent = True
        except (OSError, RuntimeError) as exc:
            error = str(exc)
        finally:
            for child in (process, removal, probe):
                if child is not None and child.returncode is None:
                    try:
                        child.kill()
                        await asyncio.wait_for(child.wait(), timeout=3)
                    except (OSError, asyncio.TimeoutError):
                        error = error or "Docker 客户端进程未能及时退出。"
            if confirmed_absent:
                snapshot_path = Path(snapshot.name).absolute()
                allowed_root = validate_lab_directory(self.workspace.parent / ".sandbox")
                if not snapshot_path.resolve().is_relative_to(allowed_root):
                    error = "测试快照清理路径越界，已保留目录。"
                else:
                    try:
                        snapshot.cleanup()
                    except OSError as exc:
                        error = "容器已停止，快照清理失败：" + str(exc)
        return error

    @staticmethod
    def _result(error_code, message, **details) -> ToolExecutionResult:
        payload = {"ok": error_code is None, "error_code": error_code, "message": message,
                   "isolation": "docker", "image": IMAGE, **details}
        content = json.dumps(payload, ensure_ascii=False)
        if error_code:
            return build_tool_error(summary=message, error_code=error_code, error_message=content,
                                    content=content, metadata=payload, tool_name="run_tests")
        return build_tool_success(summary=message, content=content, metadata=payload, tool_name="run_tests")


def build_registry(workspace: Path, docker_available: bool,
                   on_log: Callable[[str], None]) -> ToolRegistry:
    workspace = validate_lab_directory(workspace)
    registry = ToolRegistry()
    for tool in (ConfinedReadFile(workspace), ConfinedWriteFile(workspace),
                 LabList(workspace), RunTests(workspace, docker_available, on_log)):
        registry.register(tool)
    return registry

