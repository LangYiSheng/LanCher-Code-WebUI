"""确定性离线供应商；仍通过真实 SDK 工具、审批和会话运行。"""
from __future__ import annotations

import asyncio
import json
from uuid import uuid4

from lancher_code.contracts.messages import ContentBlock, StreamEvent
from lancher_code.contracts.tools import ToolCallChunk
from lancher_code.usage.models import MessageUsage

from .sample import APP, BUGGY_APP, README, TESTS


class DemoProvider:
    """从本轮真实请求历史推导步骤，支持排队后续输入与会话恢复。"""

    @staticmethod
    def _turn(request):
        index = -1
        prompt = ""
        for position, message in enumerate(request.messages):
            text = "\n".join(block.text for block in message.blocks if block.kind == "text")
            # SDK 把主机状态增量投影为 user 消息；它不能覆盖真人的任务。
            if message.role == "user" and not text.lstrip().startswith("<host_update "):
                index = position
                prompt = text
        calls = []
        results = {}
        for message in request.messages[index + 1:]:
            for block in message.blocks:
                if block.kind == "tool_use":
                    calls.append(block)
                elif block.kind == "tool_result":
                    results[block.call_id] = block
        return prompt, calls, results

    @staticmethod
    def _last_result(calls, results, name):
        relevant = [call for call in calls if call.name == name]
        return results.get(relevant[-1].call_id) if relevant else None

    @staticmethod
    def _test_payload(result):
        if result is None:
            return None
        try:
            payload = json.loads(result.text)
        except (TypeError, ValueError):
            return None
        return payload if isinstance(payload, dict) else None

    async def _text(self, request, text, slow=False):
        chunks = [text[i:i + 16] for i in range(0, len(text), 16)]
        for chunk in chunks:
            if request.cancellation_token and request.cancellation_token.is_cancelled:
                return
            yield StreamEvent(kind="text_delta", text=chunk)
            await asyncio.sleep(0.25 if slow else 0.025)
        if slow:
            # 真实等待让停止验收能够覆盖运行中的 SDK 消费者。
            for _ in range(60):
                if request.cancellation_token and request.cancellation_token.is_cancelled:
                    return
                await asyncio.sleep(0.5)
        yield StreamEvent(
            kind="message_end", response_complete=True,
            assistant_blocks=[ContentBlock.text_block(text)], usage=MessageUsage(),
        )

    async def _tools(self, request, calls, introduction):
        blocks = [ContentBlock.text_block(introduction)]
        for chunk in [introduction[i:i + 16] for i in range(0, len(introduction), 16)]:
            yield StreamEvent(kind="text_delta", text=chunk)
            await asyncio.sleep(0.025)
        for index, (name, arguments) in enumerate(calls):
            identity = "lab-" + uuid4().hex
            encoded = json.dumps(arguments, ensure_ascii=False)
            for offset in range(0, len(encoded), 512):
                if request.cancellation_token and request.cancellation_token.is_cancelled:
                    return
                yield StreamEvent(
                    kind="tool_call_delta",
                    tool_call_chunk=ToolCallChunk(
                        call_index=index,
                        provider_call_id=identity if offset == 0 else None,
                        name_delta=name if offset == 0 else "",
                        arguments_delta=encoded[offset:offset + 512],
                    ),
                )
                await asyncio.sleep(0.01)
            blocks.append(ContentBlock.tool_use_block(call_id=identity, name=name, input=arguments))
        yield StreamEvent(kind="message_end", response_complete=True,
                          assistant_blocks=blocks, stop_reason="tool_calls", usage=MessageUsage())

    async def stream_chat(self, request):
        prompt, calls, results = self._turn(request)
        names = [call.name for call in calls]
        if any(word in prompt for word in ("慢", "停止")):
            async for event in self._text(
                request, "慢速停止实验已开始。后端正持续消费真实 SDK 流；现在可以停止，或刷新页面观察连接恢复。", True):
                yield event
            return

        if "越界" in prompt:
            if not calls:
                async for event in self._tools(
                    request, [("write_file", {"path": "../outside.txt", "content": "不应写入"})],
                    "尝试一个上级目录写入，验证 SDK 审批和实验路径防护。"):
                    yield event
            else:
                result = self._last_result(calls, results, "write_file")
                text = ("越界操作被拒绝，未写入工作区外部。\n\n" + (result.text if result else "没有可用工具结果。"))
                async for event in self._text(request, text):
                    yield event
            return

        if "审批" in prompt:
            if not calls:
                async for event in self._tools(
                    request, [("run_tests", {})], "申请运行隔离测试。SDK 会等待网页中的本次批准或拒绝。"):
                    yield event
            else:
                async for event in self._text(request, self._summary(calls, results)):
                    yield event
            return

        repair = any(word in prompt for word in ("故意失败", "修复"))
        test_calls = names.count("run_tests")
        write_calls = [call for call in calls if call.name == "write_file"]
        reads = [call for call in calls if call.name == "read_file"]

        if not calls:
            next_calls = [("lab_list", {})]
            introduction = "开始 Todo 后端实验：检查文件、生成 API 和 HTTP 集成测试，然后申请 Docker 隔离测试。"
        elif "lab_list" in names and not reads:
            next_calls = [("read_file", {"path": path}) for path in ("app.py", "tests/test_api.py", "README.md")]
            introduction = "先读取目标文件；新项目中不存在的文件会被记录为工具读取失败，随后创建。"
        elif not write_calls:
            next_calls = [
                ("write_file", {"path": "app.py", "content": BUGGY_APP if repair else APP}),
                ("write_file", {"path": "tests/test_api.py", "content": TESTS}),
                ("write_file", {"path": "README.md", "content": README}),
            ]
            introduction = ("故意将创建接口状态码写成 200，让真实 HTTP 测试发现这个问题。"
                            if repair else "写入可运行的标准库 Todo API、4 项 HTTP 集成测试和说明。")
        elif not test_calls:
            errors = [results.get(call.call_id) for call in write_calls]
            if any(result is not None and result.is_error for result in errors):
                async for event in self._text(request, "文件写入未全部成功，未继续执行测试。请查看工具结果并处理原因。"):
                    yield event
                return
            next_calls = [("run_tests", {})]
            introduction = "文件已由真实 Agent 工具写入。现在申请在无网络 Docker 临时快照中运行测试。"
        elif repair and test_calls == 1:
            test = self._last_result(calls, results, "run_tests")
            payload = self._test_payload(test)
            if not payload or payload.get("error_code") != "tests_failed":
                async for event in self._text(request, self._summary(calls, results)):
                    yield event
                return
            if len(reads) == 3:
                next_calls = [("read_file", {"path": "app.py"})]
                introduction = "真实测试发现创建接口应返回 201；重新读取 app.py，准备修复。"
            elif len(write_calls) == 3:
                next_calls = [("write_file", {"path": "app.py", "content": APP})]
                introduction = "将创建成功状态码修复为 201，保留其余 API 行为。"
            else:
                fixed = results.get(write_calls[-1].call_id)
                if fixed is not None and fixed.is_error:
                    async for event in self._text(request, "修复写入失败，未再次执行测试。请查看工具结果。"):
                        yield event
                    return
                next_calls = [("run_tests", {})]
                introduction = "修复已写入。再次申请隔离运行同一组真实 HTTP 测试。"
        else:
            async for event in self._text(request, self._summary(calls, results)):
                yield event
            return

        async for event in self._tools(request, next_calls, introduction):
            yield event

    def _summary(self, calls, results):
        result = self._last_result(calls, results, "run_tests")
        payload = self._test_payload(result)
        if result is not None and not result.is_error and payload and payload.get("ok") is True:
            message = "Todo 后端已生成，Docker 中的真实 HTTP 集成测试全部通过。可以查看 app.py、tests/test_api.py 和 README.md。"
        elif payload and payload.get("error_code") == "isolation_unavailable":
            message = "项目文件已生成。Docker 当前不可用，因此没有执行生成代码，也没有宣称测试通过。"
        elif result is not None and result.is_error:
            message = "本轮测试未通过或被拒绝。请查看工具结果；没有宣称项目验收成功。\n\n" + result.text
        else:
            message = "项目文件已生成，但没有有效的成功测试结果。"
        return message + "\n\n离线演示：生成步骤由固定脚本驱动；工具、审批、事件、排队和会话均使用真实 LanCher SDK。"
