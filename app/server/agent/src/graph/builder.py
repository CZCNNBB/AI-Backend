class AgentGraphBuilder:
    """Agent 图构建器占位实现。"""

    def build(self):
        """
        构建通用 Agent 图。

        Returns:
            当前阶段返回 None；后续接入 LangGraph 时返回 compiled graph。
        """
        # 这里先留出 LangGraph 接入点，避免当前阶段过早绑定具体图结构。
        return None
