"""从 SDK 已保存的请求前缀估算上下文，不创建 Agent 或持有会话锁。"""
from copy import deepcopy
from urllib.parse import urlsplit

from lancher_code.context.offload import project_tool_results
from lancher_code.context.prefix import restore_tool
from lancher_code.context.projection import project_historical_tool_exchanges
from lancher_code.context.tokens import estimate_request
from lancher_code.contracts.messages import ChatRequest


def saved_context_usage(state, transcript, provider_config):
    context = deepcopy(state.context_management)
    prefix = context.prefix_state
    if not prefix:
        return {"tokens": None, "source": "unknown", "window": provider_config.context_window,
                "snapshot": True}
    window = prefix["context_window"]
    experimental = prefix["experimental"]
    tools = prefix["baseline_tools"] if experimental else prefix["observed_tools"]
    projected = project_tool_results(transcript, context, context_window=window)
    def messages(items):
        return project_historical_tool_exchanges(items, protocol=prefix["protocol"], model=prefix["model"])
    updates = [{"at_message": len(messages(projected[:event["anchor"]])),
                "additions": deepcopy(event["additions"]), "removals": list(event["removals"])}
               for event in prefix["tool_events"]] if experimental else []
    request = ChatRequest(
        model=prefix["model"], system=list(prefix["system"]), messages=messages(projected),
        tools=[restore_tool(value) for value in tools.values()], allow_tool_calls=True,
        reasoning_effort=state.reasoning_effort, api_mode=provider_config.api_mode,
        experimental_mcp_tool_append=experimental, tool_updates=updates,
        prompt_cache_enabled=(experimental or prefix["protocol"] == "claude"
                              and urlsplit(provider_config.base_url).hostname == "api.anthropic.com"),
    )
    estimate = estimate_request(request, context)
    return {"tokens": estimate.tokens, "source": estimate.source, "window": window, "snapshot": True}
