"""共用 TUI 配置的无界面读写适配；测试可显式替换用户主目录。"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import threading

import yaml

from lancher_code.config.loader import load_config, load_config_data
from lancher_code.config.paths import (
    get_global_config_path, get_global_mcp_config_path, get_global_permissions_path,
    get_project_mcp_config_path, get_project_permissions_path,
)
from lancher_code.config.settings import SettingsService, SettingsError
from lancher_code.config.writer import serialize_config, write_yaml_atomic
from lancher_code.errors import ConfigError
from lancher_code.mcp.config import load_mcp_config
from lancher_code.permissions.models import PermissionRule
from lancher_code.permissions.storage import PermissionStorage


class ConfigurationError(ValueError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _read_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigurationError("配置文件无法读取或 YAML 格式无效；原文件已保留。") from exc
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ConfigurationError("配置文件顶层必须是对象。")
    return raw



def _merge_values(previous, edited):
    """未提交字段保持原值；显式 null 和新值继续表达用户的修改。"""
    if isinstance(previous, dict) and isinstance(edited, dict):
        result = deepcopy(previous)
        for key, value in edited.items():
            result[key] = _merge_values(previous.get(key), value)
        return result
    return deepcopy(edited)


def _public_models(config: dict) -> dict:
    result = deepcopy(config)
    for provider in result.get("providers", {}).values():
        if not isinstance(provider, dict):
            continue
        provider["api_key_configured"] = bool(provider.get("api_key"))
        provider["api_key"] = ""
        for model in provider.get("models", {}).values():
            if isinstance(model, dict):
                model["api_key_configured"] = bool(model.get("api_key"))
                if "api_key" in model:
                    model["api_key"] = ""
    return result


def _public_mcp(servers: dict) -> dict:
    result = deepcopy(servers)
    for server in result.values():
        if not isinstance(server, dict):
            continue
        for field in ("env", "headers"):
            values = server.get(field, {})
            if isinstance(values, dict):
                server[field + "_configured"] = {key: bool(value) for key, value in values.items()}
                server[field] = {key: "" for key in values}
    return result


def _restore_key(edited: dict, old: dict, *, inherited: bool) -> dict:
    result = deepcopy(edited)
    clear = result.pop("api_key_clear", False)
    result.pop("api_key_configured", None)
    value = result.get("api_key")
    if type(clear) is not bool or value is not None and not isinstance(value, str):
        raise ConfigurationError("API Key 编辑内容无效。")
    if clear:
        if inherited:
            result.pop("api_key", None)
        else:
            result["api_key"] = ""
    elif value is None or value == "":
        if "api_key" in old:
            result["api_key"] = old["api_key"]
        else:
            result.pop("api_key", None)
    return result


def _restore_models(edited: dict, old: dict) -> dict:
    if not isinstance(edited, dict) or not isinstance(edited.get("providers"), dict):
        raise ConfigurationError("模型设置需要 providers 对象与 default_model。")
    result = deepcopy(edited)
    providers = {}
    old_providers = old.get("providers", {})
    for identity, value in result["providers"].items():
        if not isinstance(value, dict):
            raise ConfigurationError("供应商配置必须是对象。")
        previous = old_providers.get(identity, {})
        restored = _restore_key(_merge_values(previous, value), previous, inherited=False)
        model_rows = value.get("models", previous.get("models", {}))
        if not isinstance(model_rows, dict):
            raise ConfigurationError("models 必须是对象。")
        models = {}
        for model_id, model in model_rows.items():
            if not isinstance(model, dict):
                raise ConfigurationError("单个模型配置必须是对象。")
            models[model_id] = _restore_key(
                _merge_values(previous.get("models", {}).get(model_id, {}), model),
                previous.get("models", {}).get(model_id, {}), inherited=True)
        restored["models"] = models
        providers[identity] = restored
    result["providers"] = providers
    return result


def _restore_mcp(edited: dict, old: dict) -> dict:
    if not isinstance(edited, dict):
        raise ConfigurationError("MCP 设置需要服务器对象。")
    restored = {}
    for identity, value in edited.items():
        if not isinstance(value, dict):
            raise ConfigurationError("MCP 服务器配置必须是对象。")
        previous = old.get(identity, {})
        server = deepcopy({**previous, **value})
        for field in ("env", "headers"):
            server.pop(field + "_configured", None)
            clear = server.pop(field + "_clear", [])
            remove = server.pop(field + "_remove", [])
            if (not isinstance(clear, list) or not isinstance(remove, list)
                    or any(not isinstance(key, str) for key in clear + remove)):
                raise ConfigurationError("MCP 凭据清除列表必须是字段名称数组。")
            values = server.get(field, previous.get(field, {}))
            if not isinstance(values, dict):
                raise ConfigurationError("MCP env 和 headers 必须是字符串对象。")
            merged = dict(previous.get(field, {}))
            for key, content in values.items():
                if not isinstance(key, str) or not isinstance(content, str):
                    raise ConfigurationError("MCP env 和 headers 只能包含字符串。")
                if content or key not in merged:
                    merged[key] = content
            for key in clear:
                merged[key] = ""
            for key in remove:
                merged.pop(key, None)
            if merged or field in server:
                server[field] = merged
        restored[identity] = server
    return restored


class ConfigurationService:
    def __init__(self, root: Path, user_home: Path | None = None):
        self.root = Path(root).resolve()
        self.user_home = Path(user_home).expanduser().resolve() if user_home is not None else Path.home().resolve()
        self.config_path = get_global_config_path(self.user_home)
        self._lock = threading.RLock()

    def _paths(self, project_root: Path | None) -> dict[str, Path]:
        paths = {"config": self.config_path,
                 "global_mcp": get_global_mcp_config_path(self.user_home),
                 "user_rules": get_global_permissions_path(self.user_home)}
        if project_root is not None:
            paths.update(project_mcp=get_project_mcp_config_path(project_root),
                         project_rules=get_project_permissions_path(project_root))
        return paths

    def _revision(self, project_root: Path | None) -> str:
        digest = hashlib.sha256()
        for name, path in sorted(self._paths(project_root).items()):
            digest.update(name.encode())
            digest.update(str(path).encode())
            try:
                digest.update(path.read_bytes())
            except FileNotFoundError:
                digest.update(b"<missing>")
            except OSError as exc:
                raise ConfigurationError("配置文件无法读取。") from exc
        return digest.hexdigest()

    def get_config(self):
        try:
            return load_config(self.config_path)
        except ConfigError as exc:
            raise ConfigurationError("TUI 全局模型配置缺失或无效，请先完成设置。", 409) from exc

    def make_permission_storage(self, project_root: Path) -> PermissionStorage:
        return PermissionStorage(project_rules_path=get_project_permissions_path(project_root),
                                 user_rules_path=get_global_permissions_path(self.user_home))

    def get_mcp_config(self, project_root: Path):
        return load_mcp_config(project_root, home_dir=self.user_home)

    def _settings_service(self, project_root: Path | None) -> SettingsService:
        project = project_root or (self.root / "data" / "no-project")
        return SettingsService(
            config_path=self.config_path,
            global_mcp_path=get_global_mcp_config_path(self.user_home),
            project_mcp_path=get_project_mcp_config_path(project),
            permission_storage=PermissionStorage(
                user_rules_path=get_global_permissions_path(self.user_home),
                project_rules_path=get_project_permissions_path(project) if project_root is not None else None,
            ),
        )

    def snapshot(self, project_root: Path | None = None) -> dict:
        with self._lock:
            paths = self._paths(project_root)
            revision = self._revision(project_root)
            error = None
            public_config = None
            try:
                public_config = _public_models(serialize_config(self.get_config()))
            except ConfigurationError as exc:
                error = str(exc)
            storage = PermissionStorage(
                user_rules_path=paths["user_rules"], project_rules_path=paths.get("project_rules"))
            global_mcp = _read_yaml(paths["global_mcp"]).get("mcp_servers", {})
            project_mcp = _read_yaml(paths["project_mcp"]).get("mcp_servers", {}) if project_root is not None else {}
            if not isinstance(global_mcp, dict) or not isinstance(project_mcp, dict):
                raise ConfigurationError("MCP 配置需要 mcp_servers 对象。")
            return {
                "config": public_config, "configured": public_config is not None,
                "error": error, "revision": revision,
                "global_mcp": _public_mcp(global_mcp), "project_mcp": _public_mcp(project_mcp),
                "user_rules": [asdict(rule) for rule in storage.rules_for_scope("user")],
                "project_rules": [asdict(rule) for rule in storage.rules_for_scope("project")],
                "paths": {name: str(path) for name, path in paths.items()},
            }

    def save(self, payload: dict, project_root: Path | None = None) -> dict:
        if not isinstance(payload, dict):
            raise ConfigurationError("设置提交内容必须是对象。")
        domain = payload.get("domain")
        if domain not in {"models", "ui", "runtime", "execution", "mcp", "rules"}:
            raise ConfigurationError("未知设置领域。")
        data = payload.get("data", payload.get("config", payload.get(domain)))
        with self._lock:
            revision = self._revision(project_root)
            if payload.get("revision") != revision:
                raise ConfigurationError("配置已在其他窗口更新，请刷新设置后重新提交。", 409)
            paths = self._paths(project_root)
            scope = payload.get("scope")
            try:
                if domain in {"models", "ui", "runtime", "execution"}:
                    current = _read_yaml(self.config_path)
                    if not isinstance(data, dict):
                        raise ConfigurationError("设置领域内容必须是对象。")
                    candidate = deepcopy(current)
                    if domain == "models":
                        edited = _restore_models(data, current)
                        candidate["providers"] = edited["providers"]
                        if "default_model" in edited:
                            candidate["default_model"] = edited["default_model"]
                        # 首次设置可以同时提供其他领域；已有配置不会受模型表单影响。
                        if not current:
                            for key in ("ui", "runtime", "execution"):
                                if key in edited:
                                    candidate[key] = edited[key]
                    else:
                        candidate[domain] = _merge_values(current.get(domain, {}), data)
                    if domain == "ui":
                        for key in ("show_timestamps", "show_thinking_status"):
                            if key in data and type(data[key]) is not bool:
                                raise ConfigurationError("界面开关必须是布尔值。")
                    load_config_data(candidate)
                    # 保留未编辑领域的原始文本值和继承结构，只更新选中的领域。
                    if self._revision(project_root) != revision:
                        raise ConfigurationError("配置在保存前发生变化，请刷新设置。", 409)
                    write_yaml_atomic(self.config_path, candidate)
                    scope = "global"
                elif domain == "mcp":
                    if scope not in {"global", "project"}:
                        raise ConfigurationError("MCP 作用范围必须为 global 或 project。")
                    if scope == "project" and project_root is None:
                        raise ConfigurationError("请先选择项目再修改项目 MCP。")
                    path = paths["global_mcp" if scope == "global" else "project_mcp"]
                    old = _read_yaml(path).get("mcp_servers", {})
                    servers = data.get("mcp_servers", data) if isinstance(data, dict) else data
                    servers = _restore_mcp(servers, old)
                    SettingsService._validate_mcp(servers, "MCP")
                    if self._revision(project_root) != revision:
                        raise ConfigurationError("配置在保存前发生变化，请刷新设置。", 409)
                    service = self._settings_service(project_root)
                    service.save_mcp(scope, servers)
                else:
                    if scope not in {"user", "project", "global"}:
                        raise ConfigurationError("权限作用范围必须为 user 或 project。")
                    scope = "user" if scope == "global" else scope
                    if scope == "project" and project_root is None:
                        raise ConfigurationError("请先选择项目再修改项目规则。")
                    rows = data.get("rules", data) if isinstance(data, dict) else data
                    if not isinstance(rows, list):
                        raise ConfigurationError("权限规则必须是数组。")
                    rules = []
                    for row in rows:
                        if not isinstance(row, dict):
                            raise ConfigurationError("每条权限规则必须是对象。")
                        rules.append(PermissionRule(
                            match=row.get("match"), result=row.get("result", "deny"), scope=scope,
                            match_kind=row.get("match_kind", "exact"),
                            command_cwd=row.get("command_cwd"), command_shell=row.get("command_shell"),
                        ))
                    SettingsService._validate_rules(rules)
                    if self._revision(project_root) != revision:
                        raise ConfigurationError("配置在保存前发生变化，请刷新设置。", 409)
                    self._settings_service(project_root).save_rules(scope, rules)
            except ConfigurationError:
                raise
            except (ConfigError, SettingsError, ValueError, TypeError, OSError, AttributeError) as exc:
                # 不把 YAML 源行、API Key 或 MCP 环境值带到 HTTP 错误正文。
                raise ConfigurationError("设置校验或保存失败，请检查当前领域的必填项与参数格式。") from exc
            return {"saved": True, "domains": [domain], "scopes": [scope],
                    "revision": self._revision(project_root), "snapshot": self.snapshot(project_root)}
