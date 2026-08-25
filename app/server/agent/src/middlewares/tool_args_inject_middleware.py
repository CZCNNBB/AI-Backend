"""工具参数注入中间件：把可信业务上下文覆盖到指定工具调用参数。"""

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

from app.server.agent.src.graph.state import CareerAgentState

logger = logging.getLogger(__name__)


# 这里只声明系统可信参数的注入规则。key 是 MCP / 内置工具真实名称，
# value 表示“工具参数名 -> runtime.context.inputs 字段名”。
INJECTED_TOOL_ARGS: dict[str, dict[str, str]] = {
    "save_job_profile": {
        "profile_type": "profile_type",
        "user_id": "user_id",
    },
}


class ToolArgsInjectMiddleware(AgentMiddleware[CareerAgentState]):
    """在工具真正执行前注入可信业务参数。

    模型可以看见这些参数及其用途，但不需要填写；即使模型主动传值，系统也会使用
    runtime.context.inputs 中的值覆盖，防止模型修改用户归属、画像类型等业务边界。
    """

    state_schema = CareerAgentState

    def __init__(self, enabled: bool = True):
        """初始化工具参数注入中间件。

        Args:
            enabled: 是否启用参数注入。
        """
        self.enabled = enabled

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:
        """在异步工具执行前覆盖已声明的可信参数。

        Args:
            request: LangGraph 工具调用请求，包含工具名、模型参数和 Runtime Context。
            handler: 实际工具执行处理器。

        Returns:
            工具执行结果。
        """
        if not self.enabled:
            return await handler(request)

        tool_name = str(request.tool_call.get("name") or "")
        injected_mapping = INJECTED_TOOL_ARGS.get(tool_name)
        if not injected_mapping:
            return await handler(request)

        context_inputs = self._get_context_inputs(request)
        tool_args = dict(request.tool_call.get("args") or {})
        for argument_name, input_name in injected_mapping.items():
            # 系统上下文始终覆盖模型参数；字段不存在时注入 None，交由业务服务给出明确校验错误。
            tool_args[argument_name] = context_inputs.get(input_name)

        logger.info(
            "工具可信参数注入完成: tool=%s injected_args=%s run_id=%s",
            tool_name,
            sorted(injected_mapping.keys()),
            self._get_runtime_value(request, "run_id"),
        )
        modified_call = {**request.tool_call, "args": tool_args}
        return await handler(request.override(tool_call=modified_call))

    def _get_context_inputs(self, request: ToolCallRequest) -> dict[str, Any]:
        """从 ToolRuntime Context 中读取业务 inputs。"""
        context = getattr(request.runtime, "context", None)
        if isinstance(context, dict):
            inputs = context.get("inputs")
        elif hasattr(context, "model_dump"):
            inputs = context.model_dump().get("inputs")
        else:
            inputs = getattr(context, "inputs", None)
        return dict(inputs) if isinstance(inputs, dict) else {}

    def _get_runtime_value(self, request: ToolCallRequest, key: str) -> str:
        """从 ToolRuntime Context 中读取用于日志的普通字段。"""
        context = getattr(request.runtime, "context", None)
        if isinstance(context, dict):
            value = context.get(key)
        elif hasattr(context, "model_dump"):
            value = context.model_dump().get(key)
        else:
            value = getattr(context, key, None)
        return str(value or "")
