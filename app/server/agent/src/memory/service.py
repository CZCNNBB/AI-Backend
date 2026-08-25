from app.server.agent.src.runtime.context import AgentRuntimeContext


class AgentMemoryService:
    """Agent 记忆服务占位实现。"""

    async def load_memory_context(self, context: AgentRuntimeContext) -> str:
        """
        加载长期记忆上下文。

        Args:
            context: Agent 运行上下文。

        Returns:
            可注入系统提示词的记忆文本；当前阶段返回空字符串。
        """
        return ""

    async def save_interaction(self, context: AgentRuntimeContext, answer: str) -> None:
        """
        保存一次 Agent 交互到记忆系统。

        Args:
            context: Agent 运行上下文。
            answer: Agent 最终回答。
        """
        return None
