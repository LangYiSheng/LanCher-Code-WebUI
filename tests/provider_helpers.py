"""仅测试注入的确定性 Provider；运行时没有固定生成脚本。"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import json
import threading
from uuid import uuid4

from lancher_code.contracts.messages import ContentBlock, StreamEvent
from lancher_code.contracts.tools import ToolCallChunk
from lancher_code.usage.models import MessageUsage


@dataclass
class Reply:
    text: str = ''
    tools: list[tuple[str, dict]] = field(default_factory=list)
    usage: MessageUsage = field(default_factory=lambda: MessageUsage(input_tokens=7, output_tokens=3, cached_input_tokens=2))
    gate: threading.Event | None = None


class ScriptedProvider:
    def __init__(self):
        self.plans: dict[str, list[Reply]] = {}
        self.positions: dict[tuple[str, str], int] = {}
        self.requests: list[dict] = []

    @staticmethod
    def prompt(request):
        for message in reversed(request.messages):
            text = '\n'.join(block.text for block in message.blocks if block.kind == 'text')
            if (message.role == 'user' and message.control_kind is None
                    and not text.lstrip().startswith('<host_update ')):
                return text
        return ''

    async def stream_chat(self, request):
        prompt = self.prompt(request)
        identity = (request.session_id or 'unknown', prompt)
        position = self.positions.get(identity, 0)
        self.positions[identity] = position + 1
        plan = self.plans.get(prompt, [Reply(text=f'完成：{prompt}')])
        reply = plan[min(position, len(plan) - 1)]
        self.requests.append({'prompt': prompt, 'session_id': request.session_id, 'position': position,
                              'model': request.model, 'reasoning_effort': request.reasoning_effort,
                              'api_mode': request.api_mode})
        if reply.gate:
            yield StreamEvent(kind='text_delta', text='等待测试闸门。')
            while not reply.gate.is_set():
                if request.cancellation_token and request.cancellation_token.is_cancelled:
                    return
                await asyncio.sleep(0.01)
        blocks = []
        if reply.text:
            for offset in range(0, len(reply.text), 7):
                yield StreamEvent(kind='text_delta', text=reply.text[offset:offset + 7])
                await asyncio.sleep(0)
            blocks.append(ContentBlock.text_block(reply.text))
        for index, (name, arguments) in enumerate(reply.tools):
            call_id = 'test-' + uuid4().hex
            yield StreamEvent(kind='tool_call_delta', tool_call_chunk=ToolCallChunk(
                call_index=index, provider_call_id=call_id, name_delta=name,
                arguments_delta=json.dumps(arguments, ensure_ascii=False)))
            blocks.append(ContentBlock.tool_use_block(call_id=call_id, name=name, input=arguments))
        yield StreamEvent(kind='message_end', response_complete=True, assistant_blocks=blocks,
                          stop_reason='tool_calls' if reply.tools else None, usage=reply.usage)
