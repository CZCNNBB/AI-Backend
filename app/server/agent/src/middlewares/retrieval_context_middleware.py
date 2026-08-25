"""把检索工具写入的证据注入下一次模型调用。"""

import logging
import operator
from collections.abc import Awaitable, Callable
from typing import Annotated

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelRequest, ModelResponse
from langchain_core.messages import SystemMessage
from typing_extensions import NotRequired

from app.server.agent.src.graph.state import CareerAgentState

logger = logging.getLogger(__name__)


class RetrievalContextState(CareerAgentState, total=False):
    """声明检索上下文对应的 LangGraph state。

    检索工具通过 Command(update={"retrieval_context": [...]}) 写入证据。
    operator.add reducer 允许本次运行中的多次检索追加证据，而不是相互覆盖。
    """

    retrieval_context: NotRequired[Annotated[list[dict[str, str]], operator.add]]


class InjectRetrievalContextMiddleware(AgentMiddleware[RetrievalContextState]):
    """在模型调用前注入当前 Agent 运行产生的检索证据。

    Checkpointer 会按照 thread_id 持久化 state，因此 retrieval_context 中的每项证据
    必须携带 run_id。中间件只注入当前 run_id 的内容，避免同一会话上一轮检索结果
    污染后续用户问题。
    """

    state_schema = RetrievalContextState

    def __init__(self, enabled: bool = True):
        """初始化检索上下文中间件。

        Args:
            enabled: 是否启用检索证据注入。
        """
        self.enabled = enabled

    def _get_current_run_id(self, request: ModelRequest) -> str:
        """从 LangChain Runtime Context 读取当前 run_id。"""
        context = getattr(request.runtime, "context", None)
        if isinstance(context, dict):
            return str(context.get("run_id") or "")
        return str(getattr(context, "run_id", "") or "")

    def _filter_current_run_context(
        self,
        retrieval_context: object,
        current_run_id: str,
    ) -> list[str]:
        """过滤并返回只属于当前 Agent 运行的检索证据。"""
        if not isinstance(retrieval_context, list):
            return []

        items: list[str] = []
        for item in retrieval_context:
            if not isinstance(item, dict):
                continue
            if str(item.get("run_id") or "") != current_run_id:
                continue
            content = str(item.get("content") or "").strip()
            if content:
                items.append(content)
        return items

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        """在每次异步模型调用前，把当前运行的检索证据追加到系统提示词末尾。"""
        if not self.enabled:
            return await handler(request)

        # 检索结果可能被 Checkpointer 保留，因此注入前必须按本次 run_id 隔离。
        current_run_id = self._get_current_run_id(request)
        retrieval_context = (request.state or {}).get("retrieval_context", [])
        retrieval_context_items = self._filter_current_run_context(
            retrieval_context,
            current_run_id,
        )
        if not retrieval_context_items:
            return await handler(request)

        logger.info(
            "检索上下文注入成功: run_id=%s items=%s",
            current_run_id,
            len(retrieval_context_items),
        )

        # 证据放在基础系统提示词末尾，既不改变模板主体，也能让模型在下一轮读取检索内容。
        joined_context = "\n\n---\n\n".join(retrieval_context_items)
        inserted = (
            "\n\n<retrieval_context>\n"
            f"{joined_context}\n\n"
            "请仅在相关时使用以上检索证据；如果证据不足，请如实说明，不得编造。\n"
            "</retrieval_context>"
        )
        current_prompt = getattr(request.system_message, "content", "")
        new_system = SystemMessage(content=f"{current_prompt}{inserted}")
        return await handler(request.override(system_message=new_system))
