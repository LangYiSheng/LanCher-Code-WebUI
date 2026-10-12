"""复用 SDK 的纯 Python 命令定义；Web 执行映射不导入 Textual。"""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone

from lancher_code.providers.catalog import iter_model_refs, model_display_name
from lancher_code.tui.commands import (
    SessionCompletionChoice, SlashCompletionContext, create_default_slash_command_registry,
)

REGISTRY = create_default_slash_command_registry()


class CommandError(ValueError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def definitions() -> list[dict]:
    return [asdict(command) for command in REGISTRY.list_all()]


def command_catalog() -> list[dict]:
    return definitions()


def _date(value) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        result = datetime.fromisoformat(str(value))
        return result if result.tzinfo else result.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return datetime.min.replace(tzinfo=timezone.utc)


def _project_chats(manager, project_id) -> list[dict]:
    return [chat for chat in manager.chats.values() if chat.get("project_id") == project_id]


def _safe_chat(chat: dict) -> dict:
    return {key: chat.get(key) for key in
            ("id", "project_id", "sdk_session_id", "title", "updated_at", "model_ref", "archived", "status")}


def allowed_while_busy(name: str, arguments: str) -> bool:
    return (name == "tasks" or name == "session" and arguments.strip() == "stop"
            or name in {"skills", "mcp"} and arguments.strip() in {"", "list"}
            or name == "skills" and arguments.split()[:1] == ["show"])


async def complete(manager, chat_id: str, text: str) -> dict:
    chat = manager.get_chat(chat_id)
    project_id = chat["project_id"]
    sessions = tuple(
        SessionCompletionChoice(
            row["sdk_session_id"], row.get("title", ""), _date(row.get("updated_at", row.get("created_at"))),
            bool(row.get("archived")),
        )
        for row in _project_chats(manager, project_id) if row.get("sdk_session_id")
    )
    models = ()
    default_model = None
    try:
        config = manager.configuration.get_config()
        models = tuple((ref, model_display_name(config.providers, ref)) for ref in iter_model_refs(config.providers))
        default_model = config.default_model
    except ValueError:
        pass
    processes = skills = servers = ()
    # 仅在对应命令补全时请求当前会话能力，避免每次输入读取所有状态。
    if text.lstrip().startswith("/tasks"):
        response = await manager.action(chat_id, "process_list")
        rows = response.get("processes", response.get("tasks", []))
        processes = tuple((row["process_id"], row.get("description") or row.get("command", row["process_id"]))
                          for row in rows if row.get("process_id"))
    elif text.lstrip().startswith("/skills"):
        response = await manager.action(chat_id, "skills_list")
        rows = response.get("skills", [])
        skills = tuple((row.get("id") or row["name"], row.get("description") or row.get("name", ""))
                       for row in rows if row.get("id") or row.get("name"))
    elif text.lstrip().startswith("/mcp"):
        response = await manager.action(chat_id, "mcp_status")
        rows = response.get("servers", response.get("mcp", []))
        servers = tuple((row["name"], row.get("status") or row.get("state", "")) for row in rows if row.get("name"))
    effort = manager.effort_state(chat)
    context = SlashCompletionContext(
        text=text, session_choices=sessions, active_session_id=chat.get("sdk_session_id"),
        process_choices=processes, model_choices=models, skill_choices=skills, mcp_choices=servers,
        active_model_ref=chat.get("model_ref"), default_model_ref=default_model,
        execution_access=chat.get("access", chat.get("execution_access", "project")),
        effort_levels=tuple(effort['effort_levels']), active_effort=effort['reasoning_effort'],
        effort_known=effort['effort_known'],
    )
    match = REGISTRY.parse_submission(text)
    busy = chat.get("status") in {"queued", "running", "waiting_permission", "starting", "stopping", "compacting"}
    permitted = not busy or match is not None and allowed_while_busy(match.definition.name, match.arguments_text)
    return {
        "candidates": [asdict(candidate) for candidate in REGISTRY.complete(context)] if permitted else [],
        "hint": REGISTRY.hint(text) if permitted else "本轮结束后可执行命令；草稿已保留。",
        "advance_text": REGISTRY.advance_text(text), "allowed": permitted,
    }


async def execute(manager, chat, text: str, confirmed: bool = False) -> dict:
    if isinstance(chat, str):
        chat = manager.get_chat(chat)
    if not isinstance(text, str) or len(text) > 20000:
        raise CommandError("命令内容无效。")
    match = REGISTRY.parse_submission(text)
    if match is None:
        if text.lstrip().startswith("/"):
            raise CommandError("未知命令，输入 / 查看可用命令。")
        return {"handled": False, "prompt": text}
    name, arguments = match.definition.name, match.arguments_text
    REGISTRY.validate(name, arguments)
    chat_id = chat["id"]
    project_id = chat["project_id"]
    busy = chat.get("status") in {"queued", "running", "waiting_permission", "starting", "stopping", "compacting"}
    if busy and not allowed_while_busy(name, arguments):
        raise CommandError("本轮结束后才能执行此命令，草稿已保留。", 409)
    response = {"handled": True, "command": name}

    if name in {"discuss", "plan", "do"}:
        result = await manager.action(chat_id, "phase", {"phase": "execute" if name == "do" else name})
        return {**response, "result": result, "prompt": arguments or None}
    if name == "status":
        return {**response, "ui_action": "status", "result": await manager.chat_detail(chat_id)}
    if name == "model":
        if not arguments:
            return {**response, "ui_action": "model_picker"}
        return {**response, "result": await manager.action(chat_id, "model", {"model_ref": arguments})}
    if name == "effort":
        if not arguments:
            return {**response, "ui_action": "effort_picker"}
        return {**response, "result": await manager.action(chat_id, "effort", {"effort": arguments})}
    if name == "access":
        if not arguments:
            return {**response, "ui_action": "access_picker"}
        return {**response, "result": await manager.action(chat_id, "access", {"access": arguments})}
    if name == "compact":
        return {**response, "result": await manager.action(chat_id, "compact")}
    if name == "exit":
        if not confirmed:
            return {**response, "requires_confirmation": True, "ui_action": "confirm_exit",
                    "message": "结束 WebUI 本次运行并收尾所有正在执行的会话和后台进程。"}
        return {**response, "ui_action": "exit", "result": await manager.shutdown()}

    if name == "session":
        args = arguments.split(maxsplit=2)
        if not args or args[0] == "list":
            return {**response, "ui_action": "sessions",
                    "sessions": [_safe_chat(row) for row in _project_chats(manager, project_id)]}
        action = args[0]
        if action == "new":
            return {**response, "ui_action": "select_chat", "chat": await manager.create_chat(project_id)}
        if action == "stop":
            return {**response, "result": await manager.stop(chat_id, scope="session")}
        target = manager.resolve_chat(project_id, args[1])
        if action in {"archive", "remove"}:
            if target["id"] == chat_id:
                raise CommandError("请先新建或切换对话，再归档或删除当前会话。", 409)
            if not confirmed:
                return {**response, "requires_confirmation": True, "ui_action": "confirm_session",
                        "target": _safe_chat(target),
                        "message": "删除包含对话记录、计划和会话工作文件。" if action == "remove" else "归档会保留记录和工作文件。"}
            result = (await manager.remove_chat(target["id"], confirmed=True) if action == "remove"
                      else await manager.patch_chat(target["id"], {"archived": True}))
            return {**response, "result": result}
        if action == "rename":
            return {**response, "result": await manager.patch_chat(target["id"], {"title": args[2]})}
        return {**response, "ui_action": "select_chat", "chat": _safe_chat(target)}

    if name == "tasks":
        args = arguments.split()
        if not args or args[0] == "list":
            return {**response, "ui_action": "inspector_processes",
                    "result": await manager.action(chat_id, "process_list")}
        action, process_id = args
        if action in {"show", "read"}:
            result = await manager.action(chat_id, "process_read", {"process_id": process_id, "cursor": 0})
            return {**response, "ui_action": "inspector_processes", "process_id": process_id, "result": result}
        return {**response, "result": await manager.action(chat_id, "process_" + action, {"process_id": process_id})}

    if name in {"skills", "mcp"}:
        args = arguments.split(maxsplit=1)
        action = args[0] if args else "list"
        parameter = args[1] if len(args) > 1 else None
        payload = {"name": parameter} if parameter is not None else {}
        mapped_action = "mcp_status" if name == "mcp" and action == "list" else name + "_" + action
        return {**response, "ui_action": "inspector_" + name,
                "result": await manager.action(chat_id, mapped_action, payload)}

    if name == "settings":
        args = arguments.split()
        if not args or args == ["open"]:
            return {**response, "ui_action": "settings"}
        key, value = args
        snapshot = await manager.settings_snapshot(project_id=project_id)
        config = snapshot.get("config")
        if not config:
            raise CommandError("请先完成全局模型配置。", 409)
        if key == "default-model":
            domain = "models"
            data = {"providers": config["providers"], "default_model": value}
        else:
            domain = "ui"
            data = dict(config.get("ui", {}))
            field = {"theme": "theme", "thinking": "show_thinking_status", "busy-enter": "busy_enter_action"}[key]
            data[field] = value == "on" if key == "thinking" else value
        result = await manager.save_settings(
            {"domain": domain, "data": data, "scope": "global",
             "revision": snapshot["revision"], "project_id": project_id})
        return {**response, "result": result}
    raise CommandError("命令尚未接入 Web 执行器。")


class CommandService:
    def __init__(self, manager):
        self.manager = manager
        self.registry = REGISTRY

    async def complete(self, chat_id: str, text: str) -> dict:
        return await complete(self.manager, chat_id, text)

    async def execute(self, chat, text: str, confirmed: bool = False) -> dict:
        return await execute(self.manager, chat, text, confirmed)
