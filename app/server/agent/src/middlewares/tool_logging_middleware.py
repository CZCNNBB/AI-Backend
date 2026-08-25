"""工具调用日志中间件：记录工具调用入参和耗时。"""

import logging
import time
from collections.abc import Awaitable, Callable

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

from app.server.agent.src.graph.state import CareerAgentState

logger = logging.getLogger(__name__)


class ToolLoggingMiddleware(AgentMiddleware[CareerAgentState]):
    """记录工具调用入参和耗时。"""

    state_schema = CareerAgentState

    def __init__(self, enabled: bool = True):
        """初始化工具调用日志中间件。

        Args:
            enabled: 是否启用工具调用日志。
        """
        self.enabled = enabled

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:
        """拦截异步工具调用并记录耗时。"""
        if not self.enabled:
            return await handler(request)

        tool_call = request.tool_call
        tool_name = tool_call.get("name")
        tool_args = tool_call.get("args") or {}
        start_time = time.time()

        logger.info(
            "工具调用开始: name=%s arg_keys=%s",
            tool_name,
            sorted(tool_args.keys()) if isinstance(tool_args, dict) else [],
        )
        response = await handler(request)
        logger.info("工具调用结束: name=%s cost=%.3fs", tool_name, time.time() - start_time)
        return response
