"""面向表单的安全领域校验；错误只包含字段位置和固定文案。"""
from __future__ import annotations

import math
import os
from pathlib import Path
import re
from urllib.parse import urlsplit

from lancher_code.config.loader import _load_provider, _load_execution
from lancher_code.config.models import AppConfig
from lancher_code.config.writer import serialize_config
from lancher_code.errors import ConfigError
from lancher_code.providers.catalog import resolve_model
from lancher_code.providers.metadata import API_MODES, load_metadata

DEFAULTS = serialize_config(AppConfig(providers={}, default_model=''))
DOMAINS = ('models', 'ui', 'runtime', 'execution')
ENTRY_ID = re.compile(r'[\w-]+')
MCP_ID = re.compile(r'[A-Za-z0-9_-]+')


def issue(domain: str, path: list, message: str) -> dict:
    return {'domain': domain, 'path': path, 'message': message}


def _number(value, *, integer=False) -> bool:
    return type(value) is int and value > 0 if integer else (
        type(value) in (int, float) and math.isfinite(value) and value > 0)


def _text(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _url(value, *, variables=False, allow_query=False) -> bool:
    if not _text(value):
        return False
    expanded = os.path.expandvars(value.strip()) if variables else value.strip()
    if variables and re.search(r'\$\{[^}]+\}|\$[A-Za-z_]\w*', expanded):
        return True
    try:
        parsed = urlsplit(expanded)
        parsed.port
        return parsed.scheme in {'http', 'https'} and bool(parsed.hostname) and not any(char.isspace() for char in parsed.hostname) and not (
            parsed.username or parsed.password or not allow_query and (parsed.query or parsed.fragment))
    except ValueError:
        return False


def models_shape(value) -> bool:
    if not isinstance(value, dict) or not isinstance(value.get('providers'), dict):
        return False
    return all(isinstance(provider, dict) and isinstance(provider.get('models', {}), dict)
               and all(isinstance(model, dict) for model in provider.get('models', {}).values())
               for provider in value.get('providers', {}).values())


def validate_models(value, *, require_default=True) -> list[dict]:
    errors = []
    add = lambda path, text: errors.append(issue('models', path, text))
    if not isinstance(value, dict) or not isinstance(value.get('providers'), dict):
        return [issue('models', ['providers'], '供应商目录必须是对象。')]
    providers = value['providers']
    if not providers:
        add(['providers'], '请至少添加一个供应商。')
    model_refs = set()
    for identity, provider in providers.items():
        path = ['providers', identity] if isinstance(identity, str) else ['providers']
        if not isinstance(identity, str) or ENTRY_ID.fullmatch(identity) is None:
            add(path, '供应商 ID 只能包含中文、字母、数字、下划线和短横线。')
        if not isinstance(provider, dict):
            add(path, '供应商配置必须是对象。')
            continue
        start = len(errors)
        for field, label in (('name', '供应商名称'), ('protocol', '调用协议'), ('base_url', 'Base URL'), ('api_key', 'API Key')):
            if not _text(provider.get(field)):
                add(path + [field], f'请填写{label}。')
        protocol = provider.get('protocol')
        if _text(protocol) and protocol.strip().lower() not in {'openai', 'claude'}:
            add(path + ['protocol'], '请选择 OpenAI 兼容或 Anthropic 兼容协议。')
        if _text(provider.get('base_url')) and not _url(provider['base_url'], variables=True):
            add(path + ['base_url'], '请填写有效的 HTTP(S) API 基址，不包含账号、查询参数或片段。')
        if isinstance(provider.get('api_key'), str) and any(ord(char) < 32 or ord(char) == 127 for char in provider['api_key']):
            add(path + ['api_key'], 'API Key 不能包含控制字符。')
        if not _number(provider.get('timeout_seconds', 60)):
            add(path + ['timeout_seconds'], '请求超时必须是有限正数。')
        if provider.get('api_mode', 'auto') not in API_MODES:
            add(path + ['api_mode'], '请选择有效的 OpenAI 接口形式。')
        models = provider.get('models', {})
        if not isinstance(models, dict):
            add(path + ['models'], '模型目录必须是对象。')
            continue
        for model_id, model in models.items():
            model_path = path + ['models', model_id] if isinstance(model_id, str) else path + ['models']
            if not isinstance(model_id, str) or ENTRY_ID.fullmatch(model_id) is None:
                add(model_path, '模型 ID 只能包含中文、字母、数字、下划线和短横线。')
            else:
                model_refs.add(f'{identity}/{model_id}')
            if not isinstance(model, dict):
                add(model_path, '模型配置必须是对象。')
                continue
            if not _text(model.get('model_name')):
                add(model_path + ['model_name'], '请填写 API 模型名称。')
            if not isinstance(model.get('display_name', ''), str):
                add(model_path + ['display_name'], '显示名称必须是字符串。')
            for field in ('protocol', 'base_url', 'api_key'):
                item = model.get(field)
                if item is not None and not _text(item):
                    add(model_path + [field], '请填写覆盖值，或恢复继承供应商。')
            own_protocol = model.get('protocol')
            if _text(own_protocol) and own_protocol.strip().lower() not in {'openai', 'claude'}:
                add(model_path + ['protocol'], '请选择 OpenAI 兼容或 Anthropic 兼容协议。')
            if _text(model.get('base_url')) and not _url(model['base_url'], variables=True):
                add(model_path + ['base_url'], '请填写有效的 HTTP(S) API 基址。')
            for field in ('timeout_seconds', 'context_window', 'max_output_tokens'):
                if model.get(field) is not None and not _number(model[field], integer=field != 'timeout_seconds'):
                    add(model_path + [field], '请输入正整数。' if field != 'timeout_seconds' else '请求超时必须是有限正数。')
            if model.get('api_mode') is not None and model['api_mode'] not in API_MODES:
                add(model_path + ['api_mode'], '请选择有效的 OpenAI 接口形式。')
            if _number(model.get('context_window'), integer=True) and _number(model.get('max_output_tokens'), integer=True) and model['max_output_tokens'] >= model['context_window']:
                add(model_path + ['max_output_tokens'], '单次输出上限必须小于上下文窗口。')
            try:
                load_metadata(model.get('metadata'), 'metadata')
            except (ConfigError, ValueError, TypeError, AttributeError):
                add(model_path + ['metadata'], '模型能力信息无效，请移除后重新发现模型。')
        if len(errors) == start:
            try:
                loaded = _load_provider(provider, 'provider')
                for model_id in loaded.models:
                    try:
                        resolve_model({identity: loaded}, f'{identity}/{model_id}')
                    except (ConfigError, ValueError, TypeError, AttributeError) as exc:
                        # 只使用核心错误中的固定字段名，绝不回显错误原文或提交值。
                        text = str(exc)
                        field = next((key for key in ('max_output_tokens', 'context_window', 'api_key', 'base_url', 'timeout_seconds', 'model_name', 'api_mode') if key in text), 'metadata')
                        add(path + ['models', model_id, field], '该字段与当前连接或模型能力不匹配，请检查后重新保存。')
            except (ConfigError, ValueError, TypeError, AttributeError) as exc:
                text = str(exc)
                field = next((key for key in ('name', 'protocol', 'base_url', 'api_key', 'timeout_seconds', 'api_mode', 'models') if key in text), None)
                add(path + ([field] if field else []), '该字段不符合当前 SDK 的要求，请检查后重新保存。')
    if require_default:
        default = value.get('default_model')
        if not _text(default):
            add(['default_model'], '请选择新聊天默认模型。')
        elif default not in model_refs:
            add(['default_model'], '默认模型必须指向目录中存在的模型。')
    return errors


def validate_domain(domain: str, value) -> list[dict]:
    if domain == 'models':
        return validate_models(value)
    if not isinstance(value, dict):
        return [issue(domain, [], '该设置领域必须是对象。')]
    errors = []
    add = lambda path, text: errors.append(issue(domain, path, text))
    if domain == 'ui':
        for field in ('show_timestamps', 'show_thinking_status'):
            if field in value and type(value[field]) is not bool:
                add([field], '显示开关必须是布尔值。')
        for field, choices in (('theme', {'dark', 'light'}), ('busy_enter_action', {'follow_up', 'steer', 'draft'})):
            if field in value and (not isinstance(value[field], str) or value[field] not in choices):
                add([field], '请选择有效的选项。')
    elif domain == 'runtime':
        for field in ('tool_loop_limit', 'unknown_tool_streak_limit', 'output_continuation_limit'):
            if field in value and not _number(value[field], integer=True):
                add([field], '请输入正整数。')
        for field, choices in (('work_phase', {'discuss', 'plan', 'execute'}), ('execution_access', {'project', 'full'})):
            if field in value and (not isinstance(value[field], str) or value[field] not in choices):
                add([field], '请选择有效的选项。')
        if 'experimental_mcp_tool_append' in value and type(value['experimental_mcp_tool_append']) is not bool:
            add(['experimental_mcp_tool_append'], '实验开关必须是布尔值。')
        for field in ('permission_mode', 'permission_policy'):
            if field in value:
                add([field], '旧权限配置已不再支持，请使用工作阶段和访问范围。')
    elif domain == 'execution':
        limits = value.get('limits', {})
        if not isinstance(limits, dict):
            add(['limits'], '资源限制必须是对象。')
        else:
            merged = {**DEFAULTS['execution']['limits'], **limits}
            for field in DEFAULTS['execution']['limits']:
                integer = field not in {'stop_grace_seconds', 'drain_timeout_seconds'}
                if not _number(merged[field], integer=integer):
                    add(['limits', field], '请输入正整数。' if integer else '请输入有限正数。')
            if _number(merged['max_processes_per_session'], integer=True) and _number(merged['max_processes'], integer=True) and merged['max_processes_per_session'] > merged['max_processes']:
                add(['limits', 'max_processes_per_session'], '每会话进程上限不能超过应用进程上限。')
            if _number(merged['output_limit_bytes'], integer=True) and merged['output_limit_bytes'] < 256:
                add(['limits', 'output_limit_bytes'], '输出存储限制至少为 256 字节。')
            if _number(merged['max_read_chars'], integer=True) and merged['max_read_chars'] > 100000:
                add(['limits', 'max_read_chars'], '单次读取最多为 100000 字符。')
            if set(limits) - set(DEFAULTS['execution']['limits']):
                add(['limits'], '资源限制含有当前 SDK 不支持的配置项。')
        profiles = value.get('command_profiles', [])
        if not isinstance(profiles, list):
            add(['command_profiles'], '命令资源约定必须是数组。')
        else:
            names = set()
            for index, profile in enumerate(profiles):
                path = ['command_profiles', index]
                if not isinstance(profile, dict):
                    add(path, '命令资源约定必须是对象。')
                    continue
                for field in ('name', 'command_match'):
                    if not _text(profile.get(field)):
                        add(path + [field], '请填写非空字符串。')
                name = profile.get('name')
                if isinstance(name, str):
                    if name in names:
                        add(path + ['name'], '命令资源约定名称不能重复。')
                    names.add(name)
                resources = profile.get('resources')
                if not isinstance(resources, list):
                    add(path + ['resources'], '请明确填写资源数组，无资源需求请填写 []。')
                else:
                    for offset, resource in enumerate(resources):
                        sub = path + ['resources', offset]
                        if not isinstance(resource, dict):
                            add(sub, '资源约定必须是对象。')
                            continue
                        for field, choices, default in (('kind', {'path', 'process', 'project', 'external'}, None), ('mode', {'shared', 'exclusive'}, 'exclusive'), ('lifetime', {'invocation', 'process'}, 'process')):
                            if not isinstance(resource.get(field, default), str) or resource.get(field, default) not in choices:
                                add(sub + [field], '请选择有效的选项。')
                        if not _text(resource.get('key')):
                            add(sub + ['key'], '请填写资源标识。')
                        if type(resource.get('recursive', False)) is not bool or resource.get('recursive', False) and resource.get('kind') != 'path':
                            add(sub + ['recursive'], '递归开关仅用于路径资源，且必须为布尔值。')
                probe = profile.get('readiness')
                if probe is not None:
                    if not isinstance(probe, dict):
                        add(path + ['readiness'], '就绪条件必须是对象。')
                    else:
                        if probe.get('kind', 'tcp') != 'tcp':
                            add(path + ['readiness', 'kind'], '就绪条件只支持 TCP。')
                        if not isinstance(probe.get('host', '127.0.0.1'), str) or probe.get('host', '127.0.0.1') not in {'127.0.0.1', '::1', 'localhost'}:
                            add(path + ['readiness', 'host'], '就绪条件只能访问本机回环地址。')
                        if not _number(probe.get('port'), integer=True) or probe['port'] > 65535:
                            add(path + ['readiness', 'port'], '端口必须是 1 到 65535 的整数。')
                        if not _number(probe.get('timeout_ms', 30000), integer=True):
                            add(path + ['readiness', 'timeout_ms'], '超时必须是正整数。')
        if not errors:
            try:
                _load_execution(value)
            except (ConfigError, ValueError, TypeError, AttributeError):
                add(['command_profiles'], '执行配置包含当前 SDK 不支持的结构或配置项。')
    return errors


def validate_mcp(servers) -> list[dict]:
    if not isinstance(servers, dict):
        return [issue('mcp', [], 'MCP 服务目录必须是对象。')]
    errors = []
    for identity, server in servers.items():
        path = [identity] if isinstance(identity, str) else []
        add = lambda field, text: errors.append(issue('mcp', path + [field] if field else path, text))
        if not isinstance(identity, str) or MCP_ID.fullmatch(identity) is None:
            add('', '服务名称只能包含字母、数字、下划线和短横线。')
        if not isinstance(server, dict):
            add('', 'MCP 服务配置必须是对象。')
            continue
        kind = server.get('type')
        if not isinstance(kind, str) or kind not in {'stdio', 'http'}:
            add('type', '请选择 stdio 或 HTTP 传输类型。')
        enabled = server.get('enabled', True)
        if type(enabled) is not bool:
            add('enabled', '启用开关必须是布尔值。')
        if enabled is not False:
            if kind == 'stdio' and not _text(server.get('command')):
                add('command', '请填写启动命令。')
            if kind == 'http' and not _url(server.get('url'), allow_query=True):
                add('url', '请填写有效的 HTTP(S) 服务 URL。')
        for field in ('startup_timeout_seconds', 'tool_timeout_seconds', 'close_timeout_seconds'):
            if field in server and not _number(server[field]):
                add(field, '超时必须是有限正数；留空使用默认值。')
        if kind == 'stdio' and (not isinstance(server.get('args', []), list) or any(not isinstance(item, str) for item in server.get('args', []))):
            add('args', '命令参数必须是字符串数组。')
        for field in ('env', 'headers'):
            values = server.get(field, {})
            if not isinstance(values, dict) or any(not isinstance(key, str) or not isinstance(item, str) for key, item in values.items()):
                add(field, '凭据字段必须是字符串到字符串的对象。')
    return errors


def validate_rules(rows) -> list[dict]:
    if not isinstance(rows, list):
        return [issue('rules', [], '权限规则必须是数组。')]
    errors = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            errors.append(issue('rules', [index], '权限规则必须是对象。'))
            continue
        if not _text(row.get('match')):
            errors.append(issue('rules', [index, 'match'], '请填写匹配目标。'))
        if row.get('result', 'deny') != 'deny':
            errors.append(issue('rules', [index, 'result'], '持久规则只支持拒绝。'))
        if not isinstance(row.get('match_kind', 'exact'), str) or row.get('match_kind', 'exact') not in {'exact', 'glob'}:
            errors.append(issue('rules', [index, 'match_kind'], '请选择精确匹配或 Glob 模式。'))
        cwd, shell = row.get('command_cwd'), row.get('command_shell')
        if cwd is not None or shell is not None:
            if not _text(cwd) or '\0' in cwd or not Path(cwd).is_absolute():
                errors.append(issue('rules', [index, 'command_cwd'], '命令目录必须是绝对路径。'))
            if not isinstance(shell, str) or shell not in {'powershell', 'sh', 'bash'}:
                errors.append(issue('rules', [index, 'command_shell'], '请选择 powershell、sh 或 bash。'))
    return errors
