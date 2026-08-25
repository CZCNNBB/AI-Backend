"""Agent 发现平台 FastMCP Tool 并转换为 LangChain Tool 的运行时服务。"""

from typing import Any

from app.server.agent.src.mcp.client import MCPConnectionConfig, create_multi_server_client
from app.server.fastmcp.src.config import get_fastmcp_public_url
from app.server.fastmcp.src.schemas import MCPToolView
from app.server.fastmcp.src.service import MCPToolService


class AgentMCPRuntimeService:
    """负责校验 Agent 工具白名单，并从平台 MCP Endpoint 发现对应 Tool。"""

    def __init__(self, catalog_service: MCPToolService | None = None) -> None:
        """初始化 Agent MCP 运行时服务。"""
        self.catalog_service = catalog_service or MCPToolService()

    async def load_runtime_langchain_tools(self, tool_names: list[str]) -> list[Any]:
        """根据 Agent 配置加载可直接挂载的 LangChain MCP Tool。"""
        if not tool_names:
            return []

        # 数据库只用于确认工具存在且已发布；短事务关闭后才访问 MCP HTTP Endpoint。
        tool_snapshots = self.catalog_service.load_enabled_tool_snapshots(tool_names)
        return await self._load_langchain_tools_from_snapshots(tool_snapshots, tool_names)

    async def _load_langchain_tools_from_snapshots(
        self,
        tool_snapshots: list[MCPToolView],
        tool_names: list[str],
    ) -> list[Any]:
        """从统一 FastMCP Endpoint 发现工具，并恢复 Agent 配置声明顺序。"""
        if len(tool_snapshots) != len(tool_names):
            raise RuntimeError("MCP Tool 配置快照数量与 Agent 白名单不一致")

        connection = MCPConnectionConfig(
            key="platform",
            base_url=get_fastmcp_public_url(),
            transport="http",
        )
        discovered_tools = await self._fetch_mcp_tools([connection])

        tool_by_original_name: dict[str, Any] = {}
        for discovered_tool in discovered_tools:
            loaded_name = str(getattr(discovered_tool, "name", "") or "")
            original_name = self._normalize_loaded_tool_name(loaded_name, tool_names)
            if original_name:
                tool_by_original_name[original_name] = discovered_tool

        missing_names = [name for name in tool_names if name not in tool_by_original_name]
        if missing_names:
            loaded_names = [str(getattr(tool, "name", "")) for tool in discovered_tools]
            raise RuntimeError(
                f"平台 MCP Endpoint 未发现已配置工具: missing={missing_names}, loaded={loaded_names}"
            )
        return [tool_by_original_name[name] for name in tool_names]

    async def _fetch_mcp_tools(self, connections: list[MCPConnectionConfig]) -> list[Any]:
        """通过 langchain-mcp-adapters 把平台 MCP Tool 转换为 LangChain Tool。"""
        client = create_multi_server_client(connections)
        return await client.get_tools()

    @staticmethod
    def _normalize_loaded_tool_name(loaded_name: str, requested_names: list[str]) -> str | None:
        """兼容 Adapter 可能添加的服务名前缀，解析 MCP 原始 Tool 名。"""
        if loaded_name in requested_names:
            return loaded_name
        for requested_name in requested_names:
            prefixed_names = {
                f"platform_{requested_name}",
                f"platform__{requested_name}",
                f"platform.{requested_name}",
            }
            if loaded_name in prefixed_names:
                return requested_name
        return None
