from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.server.knowledge.src.services import knowledge_service


@asynccontextmanager
async def app_lifespan(app: FastAPI):
    """
    FastAPI 应用生命周期钩子。

    服务启动时执行基础设施健康检查；后续如果要加 Redis、向量库、定时任务，也统一放这里编排。
    """
    # Knowledge startup 统一检查 PostgreSQL、Milvus 和本地切片能力。
    await knowledge_service.startup()
    try:
        yield
    finally:
        # 统一关闭知识库模块持有的 HTTP 连接池与 Milvus 连接。
        await knowledge_service.close()
