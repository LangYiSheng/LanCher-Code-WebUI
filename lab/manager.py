"""宿主拥有任务，浏览器只消费持久化事件。"""
from __future__ import annotations

import asyncio
import difflib
import importlib.metadata
import json
import logging
import re
import shutil
import subprocess
import time
from contextlib import aclosing
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from lancher_code.agent.skills import SkillsService
from lancher_code.config.loader import load_config
from lancher_code.contracts.json import json_value
from lancher_code.permissions.storage import PermissionStorage
from lancher_code.providers.models import ModelDefinition, ProviderDefinition
from lancher_code.sdk import AgentConfig, PermissionResolution, RuntimeConfig, create_agent

from .demo import DemoProvider
from .tools import build_registry, resolve_lab_path, validate_lab_directory

logger = logging.getLogger(__name__)


class LabError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


@dataclass
class LabSession:
    id: str
    title: str
    mode: str
    model: str
    created_at: str
    workspace: Path
    record_dir: Path
    status: str = 'idle'
    sdk_session_id: str | None = None
    run_id: str | None = None
    result: dict | None = None
    events: list[dict] = field(default_factory=list)
    messages: list[dict] = field(default_factory=list)
    pending_permissions: dict[str, dict] = field(default_factory=dict)
    baseline: dict[str, str] = field(default_factory=dict)
    saved_queue: list[dict] = field(default_factory=list)
    agent: object | None = None
    task: asyncio.Task | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    signal: asyncio.Event = field(default_factory=asyncio.Event)
    last_progress_at: float = 0.0


class LabManager:
    def __init__(self, root: Path):
        validate_lab_directory(root)
        self.root = root.resolve()
        self.data = self.root / 'data'
        self.sessions: dict[str, LabSession] = {}
        self.live_config = None
        self.live_notice = ''
        self.docker_available = False
        self.closing = False
        self.snapshot = json.loads((self.root / 'vendor' / 'snapshot.json').read_text(encoding='utf-8-sig'))
        self._load_live_config()

    def _load_live_config(self):
        path = self.data / 'model.yaml'
        validate_lab_directory(path)
        if not path.is_file():
            self.live_notice = '在 data/model.yaml 配置模型后重启，即可使用在线模式。'
            return
        try:
            config = load_config(path).to_agent_config()
            config.runtime = RuntimeConfig(tool_loop_limit=30, execution_access='project')
            # 在线请求额度有限，工具执行仍由独立适配器约束。
            for provider in config.providers.values():
                provider.timeout_seconds = min(provider.timeout_seconds, 120)
            self.live_config = config
        except Exception:
            self.live_notice = '独立模型配置未通过校验，请检查 data/model.yaml。'

    async def start(self):
        validate_lab_directory(self.data)
        self.data.mkdir(parents=True, exist_ok=True)
        self.docker_available = await asyncio.to_thread(self._probe_docker)
        records = self.data / 'sessions'
        validate_lab_directory(records)
        records.mkdir(exist_ok=True)
        for directory in records.iterdir():
            if not re.fullmatch(r'[0-9a-f]{32}', directory.name) or directory.is_symlink() or directory.is_junction():
                continue
            path = directory / 'meta.json'
            if not path.is_file():
                continue
            try:
                meta = json.loads(path.read_text(encoding='utf-8'))
                workspace = self.data / 'workspaces' / directory.name
                validate_lab_directory(workspace)
                validate_lab_directory(directory)
                if workspace.is_symlink() or workspace.is_junction():
                    continue
                session = LabSession(directory.name, meta['title'], meta['mode'], meta['model'],
                                     meta['created_at'], workspace, directory)
                session.sdk_session_id = meta.get('sdk_session_id')
                session.run_id = meta.get('run_id')
                session.status = meta.get('status', 'idle')
                session.messages = meta.get('messages', [])
                session.result = meta.get('result')
                session.saved_queue = meta.get('queue', [])
                event_path = directory / 'events.jsonl'
                if event_path.is_file():
                    for line in event_path.read_text(encoding='utf-8').splitlines():
                        try:
                            session.events.append(json.loads(line))
                        except json.JSONDecodeError:
                            # 进程意外退出的末尾半行不能当成事件。
                            continue
                baseline_path = directory / 'baseline.json'
                if baseline_path.is_file():
                    session.baseline = json.loads(baseline_path.read_text(encoding='utf-8'))
                self.sessions[session.id] = session
                if session.status in {'running', 'waiting_permission', 'stopping'}:
                    session.status = 'interrupted'
                    self.emit(session, {'kind': 'lab_log', 'text': '上次服务在运行中退出；任务未自动重放，历史已保留。'})
                self.save(session)
            except (OSError, KeyError, ValueError):
                logger.exception('无法恢复实验会话 %s', directory.name)

    def _probe_docker(self) -> bool:
        executable = shutil.which('docker')
        if not executable:
            return False
        try:
            result = subprocess.run([executable, 'image', 'inspect', 'python:3.14-slim'],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=6)
            return result.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            return False

    def status(self) -> dict:
        models = [{'id': 'lab/demo', 'name': '演示模型 · 真实 Agent', 'mode': 'demo'}]
        if self.live_config:
            for provider_id, provider in self.live_config.providers.items():
                for model_id, model in provider.models.items():
                    models.append({'id': f'{provider_id}/{model_id}', 'name': model.display_name or model.model_name,
                                   'mode': 'live'})
        return {'name': 'LanCher Agent Lab', 'sdk_version': importlib.metadata.version('lancher-code'),
                'sdk_commit': self.snapshot['commit'], 'mode': 'demo',
                'isolation': '文件范围受限 · Python 测试使用 Docker 文件副本',
                'models': models, 'default_live_model': self.live_config.default_model if self.live_config else None,
                'live_available': self.live_config is not None, 'live_notice': self.live_notice,
                'docker_available': self.docker_available, 'max_parallel_sessions': 4}

    def get(self, session_id: str) -> LabSession:
        session = self.sessions.get(session_id)
        if session is None:
            raise LabError('会话不存在。', 404)
        return session

    def files(self, session: LabSession) -> list[dict]:
        rows = []
        if not session.workspace.exists():
            return rows
        # 不跟随目录链接，内部会话与隐藏文件不向网页暴露。
        for directory, dirs, names in session.workspace.walk(follow_symlinks=False):
            dirs[:] = [name for name in dirs if not name.startswith('.') and
                       not (directory / name).is_symlink() and not (directory / name).is_junction()]
            for name in names:
                if name.startswith('.'):
                    continue
                path = directory / name
                if path.is_symlink() or path.is_junction() or not path.is_file():
                    continue
                relative = path.relative_to(session.workspace).as_posix()
                try:
                    path = resolve_lab_path(session.workspace, relative)
                except (ValueError, OSError):
                    continue
                try:
                    size = path.stat().st_size
                    content = path.read_text(encoding='utf-8') if size <= 512_000 else None
                except (OSError, UnicodeError):
                    content = None
                    size = 0
                baseline = session.baseline.get(relative)
                state = 'added' if baseline is None else ('unchanged' if baseline == content else 'modified')
                rows.append({'path': relative, 'size': size, 'status': state})
        return sorted(rows, key=lambda row: row['path'])[:500]

    def file(self, session: LabSession, path: str) -> dict:
        try:
            target = resolve_lab_path(session.workspace, path)
            if not target.is_file():
                raise LabError('文件不存在。', 404)
            if target.stat().st_size > 512_000:
                raise LabError('文件超过预览大小限制。', 413)
            content = target.read_text(encoding='utf-8')
        except LabError:
            raise
        except (OSError, ValueError, UnicodeError) as exc:
            raise LabError('文件路径越界或无法读取。', 403) from exc
        baseline = session.baseline.get(path, '')
        diff = ''.join(difflib.unified_diff(baseline.splitlines(keepends=True), content.splitlines(keepends=True),
                                           fromfile=f'a/{path}', tofile=f'b/{path}'))
        return {'path': path, 'content': content, 'baseline': baseline, 'diff': diff}

    def summary(self, session: LabSession) -> dict:
        return {'id': session.id, 'title': session.title, 'mode': session.mode, 'model': session.model,
                'created_at': session.created_at, 'status': session.status, 'workspace': str(session.workspace),
                'sdk_session_id': session.sdk_session_id, 'run_id': session.run_id,
                'files_count': len(self.files(session)), 'queue_paused': bool(session.agent.queue_paused) if session.agent else bool(session.saved_queue)}

    def detail(self, session: LabSession) -> dict:
        messages = json_value(session.agent.messages) if session.agent else session.messages
        queue = json_value(session.agent.pending_inputs) if session.agent else session.saved_queue
        return {**self.summary(session), 'messages': messages, 'events': session.events,
                'pending_permissions': list(session.pending_permissions.values()), 'result': session.result,
                'files': self.files(session), 'queue': queue}

    def save(self, session: LabSession):
        if session.agent:
            session.messages = json_value(session.agent.messages)
            session.saved_queue = json_value(session.agent.pending_inputs)
            session.sdk_session_id = session.agent.session_id or session.sdk_session_id
            session.run_id = session.agent.run_id
        value = {**self.summary(session), 'messages': session.messages, 'result': session.result,
                 'queue': session.saved_queue}
        atomic_json(session.record_dir / 'meta.json', value)

    def emit(self, session: LabSession, data: dict):
        event = dict(data)
        if 'sequence' in event:
            event['sdk_sequence'] = event['sequence']
        event['sequence'] = session.events[-1]['sequence'] + 1 if session.events else 1
        event['timestamp'] = utc_now()
        session.events.append(event)
        validate_lab_directory(session.record_dir)
        session.record_dir.mkdir(parents=True, exist_ok=True)
        with (session.record_dir / 'events.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(event, ensure_ascii=False) + '\n')
        previous = session.signal
        session.signal = asyncio.Event()
        previous.set()

    def changed(self, session: LabSession):
        self.save(session)
        self.emit(session, {'kind': 'lab_state', 'session': self.summary(session),
                            'queue': json_value(session.agent.pending_inputs) if session.agent else session.saved_queue})

    def on_sdk_event(self, session: LabSession, event):
        if event.kind == 'progress_updated':
            now = time.monotonic()
            if now - session.last_progress_at < 0.15:
                return
            session.last_progress_at = now
        data = event.to_dict()
        if event.kind in {'progress_updated', 'assistant_text_delta'}:
            # 增量流只发增量，完整消息仍由完成事件和状态查询提供。
            data['message'] = None
        request = data.get('permission_request')
        if event.kind == 'permission_request_created' and request:
            session.pending_permissions[request['request_id']] = request
            session.status = 'waiting_permission'
        if event.kind in {'permission_request_resolved', 'permission_request_closed'}:
            resolution = data.get('permission_resolution')
            if resolution:
                session.pending_permissions.pop(resolution['request_id'], None)
            elif request:
                session.pending_permissions.pop(request['request_id'], None)
            if not session.pending_permissions and session.status == 'waiting_permission':
                session.status = 'running'
        session.sdk_session_id = event.session_id or session.sdk_session_id
        self.emit(session, data)
        if event.kind in {'progress_updated', 'assistant_text_delta'}:
            return
        if event.kind == 'tool_result_received':
            self.emit(session, {'kind': 'lab_files_changed'})
        self.save(session)

    async def create(self, *, title: str = '', mode: str = 'demo', model: str | None = None):
        if self.closing:
            raise LabError('服务正在关闭。', 503)
        if mode == 'live' and not self.live_config:
            raise LabError(self.live_notice, 409)
        selected = 'lab/demo' if mode == 'demo' else (model or self.live_config.default_model)
        allowed = {row['id'] for row in self.status()['models'] if row['mode'] == mode}
        if selected not in allowed:
            raise LabError('所选模型不存在。')
        identity = uuid4().hex
        workspace = self.data / 'workspaces' / identity
        validate_lab_directory(workspace)
        workspace.mkdir(parents=True)
        session = LabSession(identity, title.strip() or '新的实验', mode, selected, utc_now(),
                             workspace, self.data / 'sessions' / identity)
        self.sessions[identity] = session
        self.changed(session)
        return session

    async def ensure_agent(self, session: LabSession):
        if session.agent:
            return session.agent
        if session.mode == 'demo':
            config = AgentConfig(providers={'lab': ProviderDefinition(name='本地演示', protocol='openai',
                    base_url='http://127.0.0.1', api_key='offline-demo',
                    models={'demo': ModelDefinition(model_name='lab-demo')})}, default_model='lab/demo',
                    runtime=RuntimeConfig(tool_loop_limit=30, execution_access='project'))
            factory = lambda _: DemoProvider()
        else:
            config = self.live_config
            if config is None:
                raise LabError('在线模型配置不可用。', 409)
            factory = None
        empty_home = self.data / 'isolated-home' / session.id
        validate_lab_directory(empty_home)
        empty_home.mkdir(parents=True, exist_ok=True)
        agent = create_agent(config, cwd=session.workspace, model_ref=session.model, provider_factory=factory,
                             tool_registry=build_registry(session.workspace, self.docker_available,
                                 lambda text: self.emit(session, {'kind': 'lab_log', 'text': text})),
                             permission_storage=PermissionStorage(),
                             skills_service=SkillsService(session.workspace, user_root=empty_home), enable_mcp=False)
        try:
            await agent.ready()
            if session.sdk_session_id:
                agent.resume_session(session.sdk_session_id)
        except BaseException:
            await agent.close()
            raise
        session.agent = agent
        agent.subscribe(lambda event: self.on_sdk_event(session, event))
        self.save(session)
        return agent

    def capture_baseline(self, session: LabSession):
        session.baseline = {row['path']: self.file(session, row['path'])['content']
                            for row in self.files(session) if row['size'] <= 512_000}
        atomic_json(session.record_dir / 'baseline.json', session.baseline)

    async def submit(self, session: LabSession, prompt: str):
        async with session.lock:
            if session.task and not session.task.done():
                raise LabError('当前会话正在运行，请追加到队列或停止后再发送。', 409)
            if sum(bool(row.task and not row.task.done()) for row in self.sessions.values()) >= 4:
                raise LabError('已有 4 个实验并行运行，请等待一个完成。', 429)
            agent = await self.ensure_agent(session)
            if session.title == '新的实验':
                session.title = prompt.strip()[:36]
            self.capture_baseline(session)
            session.result = None
            session.status = 'running'
            self.changed(session)
            session.task = asyncio.create_task(self.consume(session, prompt), name=f'lab-turn-{session.id}')

    async def consume(self, session: LabSession, prompt: str | None):
        try:
            stream = session.agent.run_user_turn(prompt) if prompt is not None else session.agent.run_next_queued_turn()
            async with aclosing(stream):
                async for _ in stream:
                    # subscribe 是唯一事件记录入口；这里拥有实际任务消费权。
                    pass
            result = session.agent.last_result
            if result:
                session.result = result.to_dict()
                session.status = result.status
            else:
                session.status = 'failed'
                session.result = {'status': 'failed', 'text': '', 'error_text': 'Agent 未返回终止结果。'}
        except asyncio.CancelledError:
            result = session.agent.last_result
            session.result = result.to_dict() if result else {'status': 'cancelled', 'text': ''}
            session.status = 'cancelled'
        except Exception:
            logger.exception('实验任务失败 %s', session.id)
            session.status = 'failed'
            session.result = {'status': 'failed', 'text': '', 'error_text': '任务异常退出，请查看实验目录的服务日志。'}
        finally:
            session.pending_permissions.clear()
            self.emit(session, {'kind': 'lab_result', 'result': session.result})
            self.changed(session)

    async def stop(self, session: LabSession):
        async with session.lock:
            if session.agent and session.task and not session.task.done():
                session.status = 'stopping'
                self.changed(session)
                await session.agent.stop_and_wait()
                await asyncio.gather(session.task, return_exceptions=True)
            return self.summary(session)

    def resolve(self, session: LabSession, request_id: str, outcome: str):
        if not session.agent or request_id not in session.pending_permissions:
            raise LabError('审批已结束或不属于这个会话。', 409)
        resolved = session.agent.resolve_permission_request(PermissionResolution(request_id, 'allow_once' if outcome == 'allow' else 'deny'))
        if not resolved:
            raise LabError('审批已经失效。', 409)
        session.pending_permissions.pop(request_id, None)
        session.status = 'running'
        self.changed(session)

    async def enqueue(self, session: LabSession, prompt: str):
        async with session.lock:
            agent = await self.ensure_agent(session)
            if len(agent.pending_inputs) >= 20:
                raise LabError('队列已满。', 429)
            item = agent.enqueue_input(prompt)
            self.changed(session)
            return json_value(item)

    async def resume(self, session: LabSession):
        async with session.lock:
            if session.task and not session.task.done():
                raise LabError('任务仍在运行。', 409)
            agent = await self.ensure_agent(session)
            if agent.pending_inputs:
                if sum(bool(row.task and not row.task.done()) for row in self.sessions.values()) >= 4:
                    raise LabError('并行任务数量已达上限。', 429)
                self.capture_baseline(session)
                agent.resume_queue()
                session.status = 'running'
                self.changed(session)
                session.task = asyncio.create_task(self.consume(session, None), name=f'lab-resume-{session.id}')
            else:
                self.changed(session)
            return self.detail(session)

    async def events_after(self, session: LabSession, after: int):
        cursor = after
        while not self.closing:
            signal = session.signal
            pending = [event for event in session.events if event['sequence'] > cursor]
            for event in pending:
                cursor = event['sequence']
                yield event
            try:
                await asyncio.wait_for(signal.wait(), 12)
            except TimeoutError:
                yield None

    async def close(self):
        self.closing = True
        for session in self.sessions.values():
            session.signal.set()
        async def close_one(session):
            if session.agent:
                try:
                    await session.agent.close()
                    if session.task:
                        await asyncio.gather(session.task, return_exceptions=True)
                finally:
                    self.save(session)
        await asyncio.gather(*(close_one(session) for session in self.sessions.values()))


