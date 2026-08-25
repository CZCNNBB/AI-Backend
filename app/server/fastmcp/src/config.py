"""FastMCP Endpoint 的运行配置。"""

import os


def get_fastmcp_public_url() -> str:
    """返回 Agent 访问本平台 MCP Endpoint 使用的完整地址。"""
    configured_url = os.getenv("FASTMCP_PUBLIC_URL", "").strip()
    if configured_url:
        return configured_url

    # Agent 与 FastMCP 当前运行在同一个 AI-backend 进程组内，默认走本机地址。
    port = os.getenv("FASTAPI_PORT", "8090").strip() or "8090"
    # FastMCP ASGI 子应用挂载在 /mcp，实际协议路由保留尾斜杠，避免先经历 307 重定向。
    return f"http://127.0.0.1:{port}/mcp/"
