"""长期记忆占位中间件：为模型调用前后预留记忆注入入口。"""

import logging
from collections.abc import Awaitable, Callable

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelRequest, ModelResponse

from app.server.agent.src.graph.state import CareerAgentState

logger = logging.getLogger(__name__)


class MemoryPlaceholderMiddleware(AgentMiddleware[CareerAgentState]):
    """长期记忆注入占位中间件。

    当前为占位实现，后续真正启用长期记忆时，可在模型调用前后
    读取 messages 并写入记忆相关状态。
    """

    state_schema = CareerAgentState

    def __init__(self, enabled: bool = True):
        """初始化长期记忆中间件。

        Args:
            enabled: 是否启用长期记忆注入。
        """
        self.enabled = enabled

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        """拦截模型调用，为后续长期记忆注入预留入口。"""
        if not self.enabled:
            return await handler(request)

        # 后续实现：从长期记忆服务读取上下文，注入到 system_message。
        return await handler(request)
