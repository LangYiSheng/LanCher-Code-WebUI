"""共用 TUI 配置的无界面读写适配；测试可显式替换用户主目录。"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
import math
import re
from pathlib import Path
import threading

import yaml

from lancher_code.config.loader import load_config, load_config_data, _load_provider
from lancher_code.config.models import AppConfig
from lancher_code.config.paths import (
    get_global_config_path, get_global_mcp_config_path, get_global_permissions_path,
    get_project_mcp_config_path, get_project_permissions_path,
)
from lancher_code.config.settings import SettingsService, SettingsError
from lancher_code.config.writer import serialize_config, write_yaml_atomic
from lancher_code.errors import ConfigError, ProviderError, ProviderAuthError
from lancher_code.providers.discovery import ModelDiscoveryClient, ModelDiscoveryResult, discovery_connection
from lancher_code.providers.metadata import API_MODES, connection_fingerprint, load_metadata, serialize_metadata
from lancher_code.mcp.config import load_mcp_config, validate_server_config
from lancher_code.permissions.models import PermissionRule
from lancher_code.permissions.storage import PermissionStorage
from .validation import DEFAULTS, DOMAINS, ENTRY_ID, MCP_ID, issue, models_shape, validate_domain, validate_models, validate_mcp, validate_rules


class ConfigurationError(ValueError):
    def __init__(self, message: str, status: int = 400, *, issues: list[dict] | None = None):
        super().__init__(message)
        self.status = status
        self.issues = issues or []


def _read_yaml(path: Path) -> dict:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return {}
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
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


def _editable_fields(raw: dict, *, strings=(), numbers=(), booleans=(), nullable=()) -> dict:
    """只公开控件对应的标量；错误类型留给 issues，原输入不会进入响应。"""
    result = {}
    for key in strings:
        if isinstance(raw.get(key), str) or key in nullable and raw.get(key) is None and key in raw:
            result[key] = raw[key]
    for key in numbers:
        value = raw.get(key)
        if type(value) in (int, float) and math.isfinite(value) or key in nullable and value is None and key in raw:
            result[key] = value
    for key in booleans:
        if type(raw.get(key)) is bool:
            result[key] = raw[key]
    return result


def _editable_arg(value) -> bool:
    return value is None or isinstance(value, (str, bool)) or type(value) in (int, float) and math.isfinite(value)


def _public_models(config: dict) -> dict:
    result = {'providers': {}}
    if 'default_model' in config:
        result['default_model'] = config['default_model'] if isinstance(config['default_model'], str) else ''
    for identity, source in config.get('providers', {}).items():
        provider = _editable_fields(source, strings=('name', 'protocol', 'base_url', 'api_mode'), numbers=('timeout_seconds',))
        provider['api_key_configured'] = isinstance(source.get('api_key'), str) and bool(source['api_key'].strip())
        provider['api_key'] = ''
        if 'api_mode' in source and source['api_mode'] not in API_MODES:
            # Claude 连接也必须保留修复控件的存在标记，不能把非法值投影成缺省。
            provider['api_mode'] = None
        provider['models'] = {}
        for model_id, original in source.get('models', {}).items():
            model = _editable_fields(original, strings=('model_name', 'display_name', 'protocol', 'base_url', 'api_mode'),
                                     numbers=('timeout_seconds', 'context_window', 'max_output_tokens'),
                                     nullable=('protocol', 'base_url', 'api_mode', 'timeout_seconds', 'context_window', 'max_output_tokens'))
            model['api_key_configured'] = isinstance(original.get('api_key'), str) and bool(original['api_key'].strip())
            if 'api_key' in original:
                model['api_key'] = ''
            if original.get('api_mode') is not None and original['api_mode'] not in API_MODES:
                model['api_mode'] = ''
            if 'metadata' in original:
                try:
                    candidate = deepcopy(original['metadata'])
                    if isinstance(candidate, dict):
                        # SDK dataclass 的 asdict 保留 tuple；HTTP/YAML 快照则使用数组。
                        for key in ('input_modalities', 'output_modalities'):
                            if isinstance(candidate.get(key), tuple):
                                candidate[key] = list(candidate[key])
                        capabilities = candidate.get('capabilities')
                        if isinstance(capabilities, dict):
                            for key in ('thinking_types', 'effort_levels', 'endpoints'):
                                if isinstance(capabilities.get(key), tuple):
                                    capabilities[key] = list(capabilities[key])
                    metadata = load_metadata(candidate, 'metadata')
                    model['metadata'] = serialize_metadata(metadata) if metadata is not None else None
                except (ConfigError, ValueError, TypeError, AttributeError):
                    # 保留可点击的清除入口，不展示无效快照的任何原始字段。
                    model['metadata'] = {}
            provider['models'][model_id] = model
        result['providers'][identity] = provider
    return result


def public_provider(provider) -> dict:
    """沿用 SDK 序列化以保留缺省继承，只公开不含密钥的模型草稿。"""
    config = serialize_config(AppConfig(providers={'provider': provider}, default_model='provider/preview'))
    return _public_models(config)['providers']['provider']


def _public_mcp(servers: dict) -> dict:
    result = {}
    for identity, source in servers.items():
        server = _editable_fields(source, strings=('type', 'command', 'url'), booleans=('enabled',),
                                  numbers=('startup_timeout_seconds', 'tool_timeout_seconds', 'close_timeout_seconds'))
        if isinstance(source.get('args'), list) and all(_editable_arg(value) for value in source['args']):
            server['args'] = deepcopy(source['args'])
        for field in ("env", "headers"):
            values = source.get(field, {})
            if isinstance(values, dict):
                server[field + "_configured"] = {key: isinstance(value, str) and bool(value) for key, value in values.items()}
                server[field] = {key: "" for key in values}
        result[identity] = server
    return result


def _public_section(domain: str, raw: dict) -> dict:
    if domain == 'ui':
        return _editable_fields(raw, strings=('theme', 'busy_enter_action'), booleans=('show_timestamps', 'show_thinking_status'))
    if domain == 'runtime':
        return _editable_fields(raw, strings=('work_phase', 'execution_access'),
                                numbers=('tool_loop_limit', 'unknown_tool_streak_limit', 'output_continuation_limit'),
                                booleans=('experimental_mcp_tool_append',))
    return deepcopy(raw)


def _execution_shape_safe(raw: dict) -> bool:
    """JSON 编辑器只展示 SDK 已知结构；未知嵌套数据须由用户修复原文件。"""
    if set(raw) - {'limits', 'command_profiles'} or not isinstance(raw.get('limits', {}), dict):
        return False
    limits = raw.get('limits', {})
    if set(limits) - set(DEFAULTS['execution']['limits']) or any(isinstance(value, (dict, list)) for value in limits.values()):
        return False
    profiles = raw.get('command_profiles', [])
    if not isinstance(profiles, list):
        return False
    for profile in profiles:
        if not isinstance(profile, dict) or set(profile) - {'name', 'command_match', 'resources', 'readiness'}:
            return False
        if any(isinstance(profile.get(field), (dict, list)) for field in ('name', 'command_match')):
            return False
        resources = profile.get('resources', [])
        if not isinstance(resources, list):
            return False
        for resource in resources:
            if not isinstance(resource, dict) or set(resource) - {'kind', 'key', 'mode', 'recursive', 'lifetime'} or any(isinstance(value, (dict, list)) for value in resource.values()):
                return False
        probe = profile.get('readiness')
        if probe is not None and (not isinstance(probe, dict) or set(probe) - {'kind', 'host', 'port', 'timeout_ms'} or any(isinstance(value, (dict, list)) for value in probe.values())):
            return False
    return True


def _restore_key(edited: dict, old: dict, *, inherited: bool, path: list | None = None) -> dict:
    result = deepcopy(edited)
    clear = result.pop("api_key_clear", False)
    result.pop("api_key_configured", None)
    value = result.get("api_key")
    if type(clear) is not bool or value is not None and not isinstance(value, str):
        raise ConfigurationError("API Key 编辑内容无效。", issues=[issue('models', (path or []) + ['api_key'], 'API Key 必须是字符串。')])
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
    if not models_shape(edited):
        raise ConfigurationError("模型目录结构无效。", issues=validate_models(edited))
    result = deepcopy(edited)
    providers = {}
    old_providers = old.get("providers", {})
    if not isinstance(old_providers, dict):
        raise ConfigurationError('现有模型目录无法安全编辑，请先修复配置文件。')
    for identity, value in result["providers"].items():
        if not isinstance(value, dict):
            raise ConfigurationError("供应商配置必须是对象。")
        previous = old_providers.get(identity, {})
        if not isinstance(previous, dict) or not isinstance(previous.get('models', {}), dict):
            raise ConfigurationError('现有模型目录无法安全编辑，请先修复配置文件。')
        restored = _restore_key(_merge_values(previous, value), previous, inherited=False, path=['providers', identity])
        model_rows = value.get("models", previous.get("models", {}))
        if not isinstance(model_rows, dict):
            raise ConfigurationError("models 必须是对象。")
        models = {}
        for model_id, model in model_rows.items():
            if not isinstance(model, dict):
                raise ConfigurationError("单个模型配置必须是对象。")
            models[model_id] = _restore_key(
                _merge_values(previous.get("models", {}).get(model_id, {}), model),
                previous.get("models", {}).get(model_id, {}), inherited=True, path=['providers', identity, 'models', model_id])
        for model in models.values():
            # 只在用户保存模型领域时移除已废弃参数，不迁移现有会话或启动时改配置。
            model.pop('thinking', None)
            model.pop('reasoning_effort', None)
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
        # 编辑器留空代表恢复 SDK 默认；省略字段则保留原配置。
        for field in ("startup_timeout_seconds", "tool_timeout_seconds", "close_timeout_seconds"):
            if field in value and value[field] is None:
                server.pop(field, None)
        for field in ("env", "headers"):
            server.pop(field + "_configured", None)
            clear = server.pop(field + "_clear", [])
            remove = server.pop(field + "_remove", [])
            if (not isinstance(clear, list) or not isinstance(remove, list)
                    or any(not isinstance(key, str) for key in clear + remove)):
                raise ConfigurationError("MCP 凭据清除列表必须是字段名称数组。",
                                         issues=[issue('mcp', [identity, field], '凭据清除和移除列表必须是字段名称数组。')])
            values = server.get(field, previous.get(field, {}))
            if not isinstance(values, dict):
                raise ConfigurationError("MCP env 和 headers 必须是字符串对象。",
                                         issues=[issue('mcp', [identity, field], '凭据字段必须是字符串对象。')])
            merged = dict(previous.get(field, {}))
            for key, content in values.items():
                if not isinstance(key, str) or not isinstance(content, str):
                    raise ConfigurationError("MCP env 和 headers 只能包含字符串。",
                                             issues=[issue('mcp', [identity, field], '凭据字段只能包含字符串。')])
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
        # 同一个进程复用按实际连接隔离的发现缓存，设置页关闭不会清空缓存。
        self.model_discovery = ModelDiscoveryClient()
        self._discovery_auth_invalid: set[str] = set()

    def _paths(self, project_root: Path | None) -> dict[str, Path]:
        paths = {"config": self.config_path,
                 "global_mcp": get_global_mcp_config_path(self.user_home),
                 "user_rules": get_global_permissions_path(self.user_home)}
        if project_root is not None:
            paths.update(project_mcp=get_project_mcp_config_path(project_root),
                         project_rules=get_project_permissions_path(project_root))
        return paths

    def _revision(self, project_root: Path | None, *, setup: bool = False) -> str:
        digest = hashlib.sha256()
        paths = {'config': self.config_path} if setup else self._paths(project_root)
        for name, path in sorted(paths.items()):
            digest.update(name.encode())
            digest.update(str(path).encode())
            try:
                digest.update(path.read_bytes())
            except FileNotFoundError:
                digest.update(b"<missing>")
            except OSError as exc:
                # 无关领域不可读不能阻止读取或保存当前领域；目标文件仍在保存前单独读取。
                digest.update(f'<unreadable:{exc.errno}>'.encode())
        return digest.hexdigest()

    def _revision_kind(self, revision, project_root: Path | None) -> bool:
        """发现表单可来自引导或普通设置，前后检查始终使用同一版本来源。"""
        if revision == self._revision(project_root):
            return False
        if revision == self._revision(project_root, setup=True):
            return True
        raise ConfigurationError('配置已在其他窗口更新，请重新读取后再试。', 409)

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
            model_discovery=self.model_discovery,
        )

    def candidate_provider(self, payload: dict, project_root: Path | None = None):
        """发现使用表单副本；恢复留空的凭据，不要求首次配置已有默认模型。"""
        if not isinstance(payload, dict):
            raise ConfigurationError('模型发现内容必须是对象。')
        identity = payload.get('provider_id')
        if not isinstance(identity, str) or re.fullmatch(r'[\w-]+', identity) is None:
            raise ConfigurationError('请选择有效供应商标识。')
        with self._lock:
            self._revision_kind(payload.get('revision'), project_root)
            current = _read_yaml(self.config_path)
            old = current.get('providers', {})
            if not isinstance(old, dict):
                raise ConfigurationError('现有 providers 配置需要对象。')
            edited = payload.get('provider', old.get(identity))
            if not isinstance(edited, dict):
                raise ConfigurationError('请填写供应商的名称、协议、地址和 API Key。')
            try:
                restored = _restore_models({'providers': {identity: edited}}, current)['providers'][identity]
                errors = validate_models({'providers': {identity: restored}}, require_default=False)
                if errors:
                    raise ConfigurationError('供应商连接设置需要修正。', issues=errors)
                # 固定 SDK 的领域加载器能独立校验供应商，也允许尚未加入任何模型。
                return _load_provider(restored, 'provider')
            except ConfigurationError:
                raise
            except (ConfigError, ValueError, TypeError, AttributeError) as exc:
                raise ConfigurationError('供应商参数无效，请检查名称、协议、连接和模型覆盖。') from exc

    async def discover_models(self, payload: dict, project_root: Path | None = None) -> ModelDiscoveryResult:
        refresh = payload.get('refresh', False) if isinstance(payload, dict) else False
        if type(refresh) is not bool:
            raise ConfigurationError('刷新标记必须为布尔值。')
        with self._lock:
            revision_kind = self._revision_kind(payload.get('revision'), project_root)
            provider = self.candidate_provider(payload, project_root)
        fingerprint = None
        try:
            protocol, base_url, api_key, _ = discovery_connection(provider)
            fingerprint = connection_fingerprint(protocol, base_url, api_key)
            auth_invalid = fingerprint in self._discovery_auth_invalid
            result = await self.model_discovery.discover(provider, refresh=refresh or auth_invalid)
            if auth_invalid and result.stale:
                raise ConfigurationError('这份连接的认证已失效，请检查凭据后重新发现模型。', 401)
            self._discovery_auth_invalid.discard(fingerprint)
        except ProviderError as exc:
            if isinstance(exc, ProviderAuthError) and fingerprint is not None:
                self._discovery_auth_invalid.add(fingerprint)
            # SDK 发现错误已经使用固定提示，不能把远端正文、地址或凭据回传。
            raise ConfigurationError(exc.user_message, 401 if isinstance(exc, ProviderAuthError) else 400) from exc
        with self._lock:
            revision = self._revision(project_root, setup=revision_kind)
            if revision != payload.get('revision'):
                raise ConfigurationError('配置在发现期间发生变化，请刷新设置后重新发现。', 409)
        return result

    def _main_parts(self) -> tuple[dict | None, dict, dict[str, list[dict]], set[str]]:
        """各领域独立读取；结构无法映射时不生成空的可保存草稿。"""
        data, errors, unreadable = {}, {}, set()
        try:
            raw = _read_yaml(self.config_path)
        except ConfigurationError:
            for domain in DOMAINS:
                errors[domain] = [issue(domain, [], '配置文件无法读取或结构无效；请修复原文件后重新读取。')]
            return None, data, errors, set(DOMAINS)
        models = {'providers': deepcopy(raw.get('providers', {})), 'default_model': raw.get('default_model', '')}
        valid_ids = models_shape(models) and all(
            isinstance(identity, str) and ENTRY_ID.fullmatch(identity) and all(
                isinstance(model_id, str) and ENTRY_ID.fullmatch(model_id) for model_id in provider.get('models', {}))
            for identity, provider in models['providers'].items())
        if 'provider' in raw or not valid_ids:
            errors['models'] = [issue('models', ['providers'], '模型目录结构无法安全编辑，请修复原配置文件。')]
            unreadable.add('models')
        else:
            data['models'] = _public_models(models)
            errors['models'] = validate_models(models)
        for domain in ('ui', 'runtime', 'execution'):
            value = raw.get(domain, {})
            if value is None and domain in {'ui', 'runtime'}:
                value = {}
            if not isinstance(value, dict):
                errors[domain] = [issue(domain, [], '该配置领域不是对象，无法安全编辑；请修复原文件。')]
                unreadable.add(domain)
                continue
            errors[domain] = validate_domain(domain, value)
            if domain == 'execution' and not _execution_shape_safe(value):
                unreadable.add(domain)
                if not errors[domain]:
                    errors[domain] = [issue(domain, [], '执行配置含有无法安全编辑的结构，请修复原文件。')]
                continue
            data[domain] = _public_section(domain, _merge_values(DEFAULTS[domain], value))
            if domain == 'runtime' and any(key in value for key in ('permission_mode', 'permission_policy')):
                unreadable.add(domain)
        return raw, data, {key: value for key, value in errors.items() if value}, unreadable

    def setup_snapshot(self) -> dict:
        with self._lock:
            raw, data, errors, unreadable = self._main_parts()
            issues = [item for domain in DOMAINS for item in errors.get(domain, [])]
            if unreadable:
                state = 'unreadable'
            elif not any(provider.get('models') for provider in raw.get('providers', {}).values()):
                state = 'required'
            elif issues:
                state = 'repair'
            else:
                state = 'ready'
            return {'state': state, 'config_path': str(self.config_path), 'config_exists': self.config_path.exists(),
                    'revision': self._revision(None, setup=True),
                    'data': None if unreadable else data, 'issues': issues}

    def snapshot(self, project_root: Path | None = None) -> dict:
        with self._lock:
            paths = self._paths(project_root)
            raw, data, errors, unreadable = self._main_parts()
            config = {}
            for domain in DOMAINS:
                if domain in data and domain not in errors:
                    if domain == 'models':
                        config.update(data[domain])
                    else:
                        config[domain] = data[domain]
            result = {'config': config, 'configured': not errors and raw is not None,
                      'error': '主配置需要修复，请完成首次设置。' if errors else None,
                      'revision': self._revision(project_root), 'domain_errors': errors,
                      'paths': {name: str(path) for name, path in paths.items()}}
            for key in ('global_mcp', 'project_mcp'):
                if key not in paths:
                    result[key] = {}
                    continue
                try:
                    servers = _read_yaml(paths[key]).get('mcp_servers', {})
                    problems = validate_mcp(servers)
                    if problems:
                        errors[key] = problems
                    safe = isinstance(servers, dict) and all(isinstance(name, str) and MCP_ID.fullmatch(name)
                        and isinstance(server, dict) and all(isinstance(server.get(field, {}), dict) for field in ('env', 'headers'))
                        and (server.get('type') == 'http' or server.get('args') is None or
                             isinstance(server.get('args'), list) and all(_editable_arg(value) for value in server['args']))
                        for name, server in servers.items())
                    if safe:
                        result[key] = _public_mcp(servers)
                    elif not problems:
                        errors[key] = [issue('mcp', [], 'MCP 目录结构无法安全编辑，请修复原文件。')]
                except ConfigurationError:
                    errors[key] = [issue('mcp', [], 'MCP 配置文件无法读取或结构无效；原文件已保留。')]
            for key, scope in (('user_rules', 'user'), ('project_rules', 'project')):
                if key not in paths:
                    result[key] = []
                    continue
                try:
                    _read_yaml(paths[key])
                    storage = PermissionStorage(**{('user_rules_path' if scope == 'user' else 'project_rules_path'): paths[key]})
                    result[key] = [asdict(rule) for rule in storage.rules_for_scope(scope)]
                except Exception:
                    errors[key] = [issue('rules', [], '权限规则文件无法读取或结构无效；原文件已保留。')]
            return result

    @staticmethod
    def _check_issues(issues: list[dict]) -> None:
        if issues:
            raise ConfigurationError('请修正标出的设置项后再保存。', issues=issues)

    def _validate_main(self, candidate: dict) -> None:
        problems = validate_models({'providers': candidate.get('providers'), 'default_model': candidate.get('default_model')})
        if 'provider' in candidate:
            problems.append(issue('models', ['providers'], '旧单供应商配置已不再支持，请修复原配置文件。'))
        for domain in ('ui', 'runtime', 'execution'):
            value = candidate.get(domain, {})
            if value is None and domain in {'ui', 'runtime'}:
                value = {}
            problems.extend(validate_domain(domain, value))
        self._check_issues(problems)
        try:
            load_config_data(candidate)
        except (ConfigError, ValueError, TypeError, AttributeError) as exc:
            # 核心最终把关；只匹配固定领域/字段，不向 HTTP 回传异常原文。
            text = str(exc)
            domain = next((name for name in ('ui', 'runtime', 'execution') if name + '.' in text), 'models')
            fields = {'models': ('default_model', 'protocol', 'base_url', 'api_key', 'timeout_seconds', 'metadata'),
                      'ui': tuple(DEFAULTS['ui']), 'runtime': tuple(DEFAULTS['runtime']),
                      'execution': ('limits', 'command_profiles')}
            field = next((key for key in fields[domain] if key in text), None)
            raise ConfigurationError('主配置需要修正后才能保存。', issues=[issue(domain, [field] if field else [],
                                      '该字段或相关配置不符合当前 SDK 的要求，请检查后重新保存。')]) from exc

    def save(self, payload: dict, project_root: Path | None = None) -> dict:
        if not isinstance(payload, dict):
            raise ConfigurationError('设置提交内容必须是对象。')
        domain = payload.get('domain')
        if domain not in {*DOMAINS, 'setup', 'mcp', 'rules'}:
            raise ConfigurationError('未知设置领域。')
        data = payload.get('data', payload.get('config', payload.get(domain)))
        with self._lock:
            is_setup = domain == 'setup'
            revision = self._revision(project_root, setup=is_setup)
            if payload.get('revision') != revision:
                raise ConfigurationError('配置已在其他窗口更新，请重新读取后再提交。', 409)
            paths = self._paths(project_root)
            scope = payload.get('scope')
            try:
                if domain in {*DOMAINS, 'setup'}:
                    current = _read_yaml(self.config_path)
                    if self.setup_snapshot()['state'] == 'unreadable':
                        raise ConfigurationError('原配置无法安全编辑，请先修复文件后重新读取。', 409)
                    if not isinstance(data, dict):
                        self._check_issues([issue(domain, [], '设置内容必须是对象。')])
                    candidate = deepcopy(current)
                    if is_setup:
                        if 'models' in data:
                            edited = _restore_models(data['models'], current)
                            candidate['providers'] = edited['providers']
                            if 'default_model' in edited:
                                candidate['default_model'] = edited['default_model']
                        for key in ('ui', 'runtime', 'execution'):
                            if key in data:
                                candidate[key] = _merge_values(current.get(key, {}), data[key])
                        domains = list(DOMAINS)
                    elif domain == 'models':
                        edited = _restore_models(data, current)
                        candidate['providers'] = edited['providers']
                        if 'default_model' in edited:
                            candidate['default_model'] = edited['default_model']
                        domains = [domain]
                    else:
                        candidate[domain] = _merge_values(current.get(domain, {}), data)
                        domains = [domain]
                    self._validate_main(candidate)
                    if self._revision(project_root, setup=is_setup) != revision:
                        raise ConfigurationError('配置在保存前发生变化，请重新读取。', 409)
                    write_yaml_atomic(self.config_path, candidate)
                    scope = 'global'
                elif domain == 'mcp':
                    if scope not in {'global', 'project'}:
                        raise ConfigurationError('MCP 作用范围必须为 global 或 project。')
                    if scope == 'project' and project_root is None:
                        raise ConfigurationError('请先选择项目再修改项目 MCP。')
                    path = paths['global_mcp' if scope == 'global' else 'project_mcp']
                    raw = _read_yaml(path)
                    old = raw.get('mcp_servers', {})
                    if not isinstance(old, dict):
                        raise ConfigurationError('原 MCP 目录无法安全编辑，请先修复文件。')
                    servers = data.get('mcp_servers', data) if isinstance(data, dict) else data
                    if not isinstance(servers, dict) or any(not isinstance(row, dict) for row in servers.values()):
                        self._check_issues(validate_mcp(servers))
                    servers = _restore_mcp(servers, old)
                    self._check_issues(validate_mcp(servers))
                    # 前面的多错误校验已覆盖 timeout，避开 SDK 的 TUI 字段映射缺项。
                    for name, server in servers.items():
                        validate_server_config(name, server)
                    if self._revision(project_root) != revision:
                        raise ConfigurationError('配置在保存前发生变化，请重新读取。', 409)
                    write_yaml_atomic(path, {**raw, 'mcp_servers': servers})
                    domains = ['mcp']
                else:
                    if scope not in {'user', 'project', 'global'}:
                        raise ConfigurationError('权限作用范围必须为 user 或 project。')
                    scope = 'user' if scope == 'global' else scope
                    if scope == 'project' and project_root is None:
                        raise ConfigurationError('请先选择项目再修改项目规则。')
                    rows = data.get('rules', data) if isinstance(data, dict) else data
                    self._check_issues(validate_rules(rows))
                    path = paths['user_rules' if scope == 'user' else 'project_rules']
                    raw = _read_yaml(path)
                    rules = [PermissionRule(match=row.get('match'), result=row.get('result', 'deny'), scope=scope,
                                            match_kind=row.get('match_kind', 'exact'), command_cwd=row.get('command_cwd'),
                                            command_shell=row.get('command_shell')) for row in rows]
                    if self._revision(project_root) != revision:
                        raise ConfigurationError('配置在保存前发生变化，请重新读取。', 409)
                    write_yaml_atomic(path, {**raw, **SettingsService._rules_data(rules)})
                    domains = ['rules']
            except ConfigurationError:
                raise
            except (ConfigError, SettingsError, ValueError, TypeError, OSError, AttributeError) as exc:
                raise ConfigurationError('当前设置无法保存，请检查字段或文件访问权限。',
                                         issues=[issue(domain, [], '设置不符合当前 SDK 要求，或配置文件无法写入。')]) from exc
            return {'saved': True, 'domains': domains, 'scopes': [scope],
                    'revision': self._revision(project_root, setup=is_setup),
                    'snapshot': self.setup_snapshot() if is_setup else self.snapshot(project_root)}
