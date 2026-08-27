import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import app.bootstrap
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.common.core.exceptions import register_exception_handlers
from app.common.core.lifespan import app_lifespan
from app.common.schemas.result import Result
from app.server.agent.api import router as agent_router
from app.server.file.api import router as file_router
from app.server.fastmcp.api import router as fastmcp_router
from app.server.fastmcp.src.server import fastmcp_http_app, fastmcp_registry
from app.server.knowledge.api import router as knowledge_router
from app.server.platform.api import router as platform_router


@asynccontextmanager
async def combined_app_lifespan(app: FastAPI):
    """组合业务基础设施与 FastMCP Streamable HTTP 的生命周期。"""
    async with app_lifespan(app):
        # FastMCP 的动态 Tool 只在启动阶段读取一次数据库；后续管理接口负责热更新。
        fastmcp_registry.reload_from_database()
        async with fastmcp_http_app.lifespan(app):
            yield


def create_app() -> FastAPI:
    """创建同时提供业务 API 和 MCP Endpoint 的 FastAPI 应用。"""
    app = FastAPI(lifespan=combined_app_lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=False, allow_methods=["*"], allow_headers=["*"])
    register_exception_handlers(app)
    app.include_router(agent_router, prefix="/agent", tags=["agent service"])
    app.include_router(file_router, tags=["file service"])
    app.include_router(knowledge_router, tags=["knowledge service"])
    app.include_router(fastmcp_router, prefix="/fastmcp", tags=["mcp platform"])
    app.include_router(platform_router, prefix="/platform", tags=["business platform"])

    # MCP 协议流量统一进入 /mcp；管理接口继续使用 /fastmcp/tools/*。
    app.mount("/mcp", fastmcp_http_app, name="fastmcp-protocol")

    @app.get("/")
    def root_endpoint():
        """返回基础服务健康信息。"""
        return Result.success({"message": "AI-backend", "status": "ok"})

    return app


def print_routes(app: FastAPI) -> None:
    """打印已注册路由，供本地启动检查。"""
    print("Registered AI-backend routes:")
    for route in app.routes:
        print(route.path if hasattr(route, "path") else route)


def print_startup_banner() -> None:
    """打印 AI-backend 本地启动信息。"""
    host = os.getenv("FASTAPI_HOST", "127.0.0.1")
    port = os.getenv("FASTAPI_PORT", "8090")
    print(f"AI-backend starting: http://{host}:{port}")
    print("Public modules: /agent, /file, /knowledge, /fastmcp, /mcp")


if __name__ == "__main__":
    app = create_app()
    print_startup_banner()
    print_routes(app)
    uvicorn.run(
        "app.main:create_app",
        host=os.getenv("FASTAPI_HOST", "127.0.0.1"),
        port=int(os.getenv("FASTAPI_PORT", 8090)),
        # Windows 默认 ProactorEventLoop 不支持 psycopg3 异步连接，使用项目统一工厂。
        loop="app.bootstrap:create_event_loop",
        workers=1,
        reload=True,
        factory=True,
    )
