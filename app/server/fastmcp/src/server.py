"""AI-backend 内嵌的 FastMCP Server 与 HTTP 应用。"""

from fastmcp import FastMCP

from app.server.fastmcp.src.registry import FastMCPToolRegistry


# 整个平台只有一个 FastMCP Server；数据库中的每条 API 配置会成为其中一个动态 Tool。
fastmcp_server = FastMCP(
    name="AI-backend MCP Platform",
    instructions="由平台配置生成的外部业务 HTTP API 工具。",
    on_duplicate="replace",
)
fastmcp_registry = FastMCPToolRegistry(fastmcp_server)

# 使用无状态 Streamable HTTP，避免会话状态粘在单个 Web 进程上。
fastmcp_http_app = fastmcp_server.http_app(
    path="/",
    transport="http",
    stateless_http=True,
    json_response=True,
)
