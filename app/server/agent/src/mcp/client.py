from dataclasses import dataclass
from typing import Any

from langchain_mcp_adapters.client import MultiServerMCPClient

from app.server.agent.src.mcp.runtime_context_interceptor import MCPRuntimeContextInterceptor


@dataclass(frozen=True)
class MCPConnectionConfig:
    """运行时 MCP 连接配置。

    这不是数据库模型，只是为了在服务层内部按 base_url + transport 分组后创建 MCP 客户端。
    """

    key: str
    base_url: str
    transport: str = "http"
    auth_config: dict[str, Any] | None = None


def build_mcp_connection_config(connection: MCPConnectionConfig) -> dict[str, Any]:
    """把内部连接配置转换为 langchain-mcp-adapters 的单服务配置。"""
    config: dict[str, Any] = {
        "transport": connection.transport,
        "url": connection.base_url,
    }

    # 第一阶段只保留认证配置透传能力，具体认证协议后续按实际 MCP 服务补齐。
    if connection.auth_config:
        config.update(connection.auth_config)
    return config


def create_multi_server_client(connections: list[MCPConnectionConfig]) -> MultiServerMCPClient:
    """根据 MCP 连接配置创建 MultiServerMCPClient。"""
    server_configs = {connection.key: build_mcp_connection_config(connection) for connection in connections}
    return MultiServerMCPClient(
        server_configs,
        tool_interceptors=[MCPRuntimeContextInterceptor()],
    )
