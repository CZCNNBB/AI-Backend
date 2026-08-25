from typing import Any

from app.server.agent.src.tools.base import AgentToolDefinition


class AgentToolRegistry:
    """Agent 工具注册中心。"""

    def __init__(self):
        """
        初始化工具注册中心。
        """
        self._tools: dict[str, AgentToolDefinition] = {}

    def register(self, tool: AgentToolDefinition) -> None:
        """
        注册一个 Agent 工具。

        Args:
            tool: 工具定义对象。
        """
        self._tools[tool.name] = tool

    def has_tool(self, name: str) -> bool:
        """
        判断工具是否已经注册。

        Args:
            name: 工具名称。

        Returns:
            工具存在时返回 True。
        """
        return name in self._tools

    def get_tool(self, name: str) -> Any:
        """
        根据名称获取工具函数或工具对象。

        Args:
            name: 工具名称。

        Returns:
            工具函数引用；如果工具不存在则返回 None。
        """
        tool = self._tools.get(name)
        return tool.callable_ref if tool else None

    def get_all_tools(self) -> list[Any]:
        """
        获取全部已注册工具。

        Returns:
            全部工具函数引用列表。
        """
        return [tool.callable_ref for tool in self._tools.values() if tool.callable_ref is not None]

    def list_definitions(self) -> list[AgentToolDefinition]:
        """
        获取全部工具定义。

        Returns:
            已注册工具定义列表。
        """
        return list(self._tools.values())
    def list_tools(self) -> list[str]:
        """
        获取全部已注册工具名称。

        Returns:
            工具名称列表。
        """
        return list(self._tools.keys())
