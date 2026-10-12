"""模型发现与草稿合并；发现结果只留在当前宿主内存，不直接写共享配置。"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import asdict, dataclass
from pathlib import Path
from time import monotonic
from uuid import uuid4

from lancher_code.errors import ConfigError, ProviderError, ProviderAuthError
from lancher_code.providers.catalog import merge_discovered_models, models_on_connection
from lancher_code.providers.discovery import ModelDiscoveryResult, discovery_connection
from lancher_code.providers.metadata import connection_fingerprint, serialize_metadata

from .configuration import ConfigurationError, _public_models


@dataclass(frozen=True)
class DiscoveryTicket:
    provider_id: str
    scope: str
    revision: str
    result: ModelDiscoveryResult
    expires: float


class DiscoveryService:
    def __init__(self, configuration, *, clock=monotonic, ttl=900, limit=32):
        self.configuration = configuration
        self.clock, self.ttl, self.limit = clock, ttl, limit
        self.tickets: OrderedDict[str, DiscoveryTicket] = OrderedDict()

    def _prune(self):
        now = self.clock()
        for token, ticket in list(self.tickets.items()):
            if ticket.expires <= now:
                del self.tickets[token]
        while len(self.tickets) > self.limit:
            self.tickets.popitem(last=False)

    @staticmethod
    def _scope(project_root):
        return str(Path(project_root).resolve()) if project_root is not None else ''

    async def discover(self, payload: dict, project_root=None) -> dict:
        self._prune()
        provider = self.configuration.candidate_provider(payload, project_root)
        try:
            protocol, base_url, api_key, _ = discovery_connection(provider)
        except ProviderError as exc:
            raise ConfigurationError(exc.user_message, 401 if isinstance(exc, ProviderAuthError) else 400) from exc
        fingerprint = connection_fingerprint(protocol, base_url, api_key)
        try:
            result = await self.configuration.discover_models(payload, project_root)
        except ConfigurationError as exc:
            if exc.status == 401:
                # 认证被拒绝后，这个身份的旧列表及尚未合并的票据一起失效。
                for token, ticket in list(self.tickets.items()):
                    if ticket.result.fingerprint == fingerprint:
                        del self.tickets[token]
            raise
        # 网络请求期间可能发生外部配置修改，不能把旧连接结果套到新草稿。
        provider = self.configuration.candidate_provider(payload, project_root)
        protocol, base_url, api_key, _ = discovery_connection(provider)
        fingerprint = connection_fingerprint(protocol, base_url, api_key)
        if result.fingerprint != fingerprint:
            raise ConfigurationError('连接已变化，请重新发现模型。', 409)
        token = uuid4().hex
        self.tickets[token] = DiscoveryTicket(payload['provider_id'], self._scope(project_root),
            payload['revision'], result, self.clock() + self.ttl)
        self._prune()
        return {'discovery_id': token, 'models': [serialize_metadata(model) for model in result.models],
                'fetched_at': result.fetched_at, 'cached': result.cached, 'stale': result.stale,
                'notice': result.notice, 'existing': list(models_on_connection(provider, fingerprint))}

    def merge(self, payload: dict, project_root=None) -> dict:
        self._prune()
        ticket = self.tickets.get(payload['discovery_id'])
        if ticket is None:
            raise ConfigurationError('模型发现结果已过期，请重新发现后加入。', 409)
        if (ticket.provider_id != payload['provider_id'] or ticket.scope != self._scope(project_root)
                or ticket.revision != payload['revision']):
            raise ConfigurationError('模型发现结果与当前编辑不一致，请重新发现。', 409)
        provider = self.configuration.candidate_provider(payload, project_root)
        try:
            protocol, base_url, api_key, _ = discovery_connection(provider)
        except ProviderError as exc:
            raise ConfigurationError(exc.user_message, 401 if isinstance(exc, ProviderAuthError) else 400) from exc
        if connection_fingerprint(protocol, base_url, api_key) != ticket.result.fingerprint:
            raise ConfigurationError('连接已变化，请重新发现后加入。', 409)
        try:
            merged, added, updated = merge_discovered_models(provider, ticket.result.models, payload['selected_ids'])
        except (ConfigError, ValueError, TypeError) as exc:
            raise ConfigurationError('所选模型与当前发现结果不一致，请重新选择。') from exc
        # 设置草稿必须保留显式 None/空值；SDK 落盘序列化会省略这些继承与清空意图。
        raw = {'providers': {payload['provider_id']: asdict(merged)}}
        public = _public_models(raw)['providers'][payload['provider_id']]
        before = payload['provider']
        if 'api_key_clear' in before:
            public['api_key_clear'] = before['api_key_clear']
        for model_id, model in merged.models.items():
            if model.api_key is None:
                public['models'][model_id].pop('api_key', None)
            edited = before.get('models', {}).get(model_id, {})
            if 'api_key_clear' in edited:
                public['models'][model_id]['api_key_clear'] = edited['api_key_clear']
        return {'provider': public, 'added': added, 'updated': updated}
