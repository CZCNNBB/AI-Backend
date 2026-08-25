"""工具异常处理中间件：将工具异常转换为 ToolMessage，避免整个 Agent 流程崩溃。"""

import logging
from collections.abc import Awaitable, Callable

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage
from langgraph.errors import GraphBubbleUp
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

from app.server.agent.src.config import get_agent_runtime_settings
from app.server.agent.src.graph.state import CareerAgentState

logger = logging.getLogger(__name__)


class ToolErrorHandlerMiddleware(AgentMiddleware[CareerAgentState]):
    """把普通工具异常转换成 ToolMessage，避免整个 Agent 流程直接崩掉。"""

    state_schema = CareerAgentState

    def __init__(self, enabled: bool = True, max_error_length: int | None = None):
        """初始化工具异常处理中间件。

        Args:
            enabled: 是否启用异常处理。
            max_error_length: 错误信息最大长度，超过则截断。
        """
        self.enabled = enabled
        self.max_error_length = (
            max_error_length or get_agent_runtime_settings().tool_error_max_length
        )

    def _build_error_message(self, request: ToolCallRequest, error: Exception) -> ToolMessage:
        """根据工具异常构造错误 ToolMessage。"""
        tool_name = str(request.tool_call.get("name") or "unknown_tool")
        tool_call_id = str(request.tool_call.get("id") or "missing_tool_call_id")
        detail = str(error).strip() or error.__class__.__name__
        if len(detail) > self.max_error_length:
            detail = detail[:self.max_error_length - 3] + "..."

        return ToolMessage(
            content=f"Error: Tool '{tool_name}' failed with {error.__class__.__name__}: {detail}",
            tool_call_id=tool_call_id,
            name=tool_name,
            status="error",
        )

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:
        """拦截异步工具调用异常。"""
        if not self.enabled:
            return await handler(request)

        try:
            return await handler(request)
        except GraphBubbleUp:
            raise
        except Exception as error:
            logger.exception("工具执行失败: name=%s", request.tool_call.get("name"))
            return self._build_error_message(request, error)
