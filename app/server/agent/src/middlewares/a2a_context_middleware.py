"""A2A 上下文中间件：获取子 Agent 元信息并注入到 system prompt。"""

import logging
from collections.abc import Awaitable, Callable

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelRequest, ModelResponse
from langchain_core.messages import SystemMessage

from app.server.agent.src.graph.state import CareerAgentState

logger = logging.getLogger(__name__)


class A2AAgentContextMiddleware(AgentMiddleware[CareerAgentState]):
    """把本次允许调用的子 Agent 列表注入系统提示词。

    这个中间件只负责“告诉主 Agent 当前有哪些子 Agent 可以调用”，
    真正的调用动作由 a2a_call 工具完成，调用权限也会在工具侧再次校验。

    设计上分成两层：
    1. 中间件注入可读上下文，让模型知道可选子 Agent 的名称、ID、描述。
    2. 工具侧做硬校验，避免模型幻觉出未授权 agent_id 后仍然能执行。
    """

    state_schema = CareerAgentState

    def __init__(self):
        """初始化 A2A 上下文中间件。

        _metas 用于缓存本次 Agent 运行可调用的子 Agent 元信息。
        同一次 Agent 运行中可能发生多轮模型调用，如果每轮都查 DB，
        会增加不必要的数据库访问，所以首次模型调用时加载，后续复用。
        """
        self._metas: list[dict[str, str]] | None = None
        self.enabled = True

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        """每次模型调用前检查并注入 A2A 上下文。

        Args:
            request: LangChain 传入的模型调用请求，包含 runtime context、state 和 system_message。
            handler: 后续模型调用处理器，必须把修改后的 request 继续交给它执行。

        Returns:
            模型调用结果。没有可用子 Agent 时不修改 request，直接透传。
        """
        if not self.enabled:
            return await handler(request)

        # 第一次模型调用时读取 runtime context 中的白名单，并查询模板表拿到展示信息。
        # 这里不直接相信前端传入的 ID，而是通过模板表再次确认这些子 Agent 存在且可被调用。
        if self._metas is None:
            sub_agent_list = self._get_sub_agent_list(request)
            self._metas = await self._load_sub_agent_metas(sub_agent_list) if sub_agent_list else []

        # 当前运行没有配置子 Agent，或者配置的子 Agent 都不可用时，中间件不做任何注入。
        if not self._metas:
            return await handler(request)

        # 把可调用子 Agent 信息追加到 system prompt 尾部。
        # 这样模型在决定是否调用 a2a_call 时，可以看到合法 agent_id 和各子 Agent 职责。
        injected = self._build_a2a_prompt(self._metas)
        current_prompt = getattr(request.system_message, "content", "")
        new_system = SystemMessage(content=f"{current_prompt}\n\n{injected}")
        return await handler(request.override(system_message=new_system))

    def _get_sub_agent_list(self, request: ModelRequest) -> list[str]:
        """从 LangChain runtime context 中读取本次允许调用的子 Agent ID 列表。

        Args:
            request: LangChain 模型调用请求。

        Returns:
            清理后的 agent_id 列表。context 不存在或字段为空时返回空列表。
        """
        context = getattr(request.runtime, "context", None)
        if context is None:
            return []
        if isinstance(context, dict):
            value = context.get("a2a_sub_agent_list") or []
        else:
            value = getattr(context, "a2a_sub_agent_list", []) or []
        return [str(agent_id) for agent_id in value if str(agent_id).strip()]

    async def _load_sub_agent_metas(self, agent_ids: list[str]) -> list[dict[str, str]]:
        """从 DB 查询可用子 Agent 的名称和描述。

        Args:
            agent_ids: 本次运行允许调用的子 Agent ID 白名单。

        Returns:
            可注入到 system prompt 的子 Agent 元信息列表。
            不存在、已删除、未声明 is_sub_agent=true 的模板会被跳过。
        """
        from app.common.db.postgres_db import get_db_session
        from app.server.agent.src.templates.service import AgentTemplateService

        metas: list[dict[str, str]] = []
        with get_db_session() as db:
            template_service = AgentTemplateService()
            for agent_id in agent_ids:
                template = template_service.get_template(db, agent_id)
                if template is None:
                    logger.warning("A2A 子 Agent 未找到: agent_id=%s", agent_id)
                    continue

                # 只有模板显式声明 is_sub_agent=true，才允许被作为子 Agent 暴露给主 Agent。
                # 这可以避免普通对话 Agent 被误配置进 A2A 列表后直接参与内部调用。
                if not template.config.is_sub_agent:
                    logger.warning("A2A 子 Agent 未启用: agent_id=%s", agent_id)
                    continue

                metas.append({
                    "agent_id": template.agent_id,
                    "agent_name": template.agent_name,
                    "description": template.description or "",
                })
        return metas

    def _build_a2a_prompt(self, metas: list[dict[str, str]]) -> str:
        """构建注入 system prompt 的 A2A 上下文文本。

        Args:
            metas: 已通过模板表校验的子 Agent 元信息。

        Returns:
            带有 <a2a_instruct> 标签的提示词片段。
        """
        agent_lines = []
        for meta in metas:
            agent_lines.append(
                f"- {meta['agent_name']}（agent_id: {meta['agent_id']}）：{meta['description']}"
            )

        return (
            "<a2a_instruct>\n"
            "你可以调用以下子 Agent 来完成子任务：\n"
            + "\n".join(agent_lines)
            + "\n\n使用规则：\n"
            "1. 只有确实需要拆分子任务时，才使用 a2a_call 工具调用子 Agent。\n"
            "2. 传入的 query 应清晰、具体，包含子 Agent 完成任务所需的全部信息。\n"
            "3. 子 Agent 返回文本结果后，你需要整合结果再回复用户。\n"
            "4. 只能调用上述列表中的 agent_id。\n"
            "</a2a_instruct>"
        )
