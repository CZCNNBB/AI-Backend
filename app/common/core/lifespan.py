from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.server.agent.src.checkpoint import agent_checkpoint_service
from app.server.file.src.service.file_cleanup_manager import temporary_file_cleanup_manager
from app.server.knowledge.src.services import knowledge_service


@asynccontextmanager
async def app_lifespan(app: FastAPI):
    """
    FastAPI 应用生命周期钩子。

    服务启动时执行基础设施健康检查；后续如果要加 Redis、向量库、定时任务，也统一放这里编排。
    """
    # Checkpointer 必须在接收第一个 Agent 请求前完成连接池和官方表迁移初始化。
    await agent_checkpoint_service.startup()
    try:
        try:
            # Knowledge startup 统一检查 PostgreSQL、Milvus 和本地切片能力。
            await knowledge_service.startup()
            await temporary_file_cleanup_manager.startup()
            try:
                yield
            finally:
                # 文件清理任务必须在数据库基础设施关闭前停止。
                await temporary_file_cleanup_manager.close()
        finally:
            # 即使 Knowledge 在启动中途失败，也要清理由它持有的部分初始化资源。
            await knowledge_service.close()
    finally:
        # 即使知识库启动失败，也必须释放已经打开的 Checkpointer 连接池。
        await agent_checkpoint_service.close()
