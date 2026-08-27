import asyncio
import os

from dotenv import load_dotenv

from app.common.core.logging_config import configure_application_logging


def create_event_loop() -> asyncio.AbstractEventLoop:
    """创建兼容当前平台的事件循环，Windows 固定使用 SelectorEventLoop。"""
    if os.name == "nt" and hasattr(asyncio, "SelectorEventLoop"):
        return asyncio.SelectorEventLoop()
    return asyncio.new_event_loop()


# psycopg3 的异步连接和 AsyncConnectionPool 在 Windows 下不支持 ProactorEventLoop。
# 当前后端没有 asyncio 子进程或 Playwright 调用，因此统一使用 SelectorEventLoop，
# 保证 FastAPI、LangGraph Checkpointer 和本地验收脚本使用相同的事件循环模型。
if os.name == "nt" and hasattr(asyncio, "WindowsSelectorEventLoopPolicy"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# 加载 backend/.env 中的环境变量。
load_dotenv(override=True)

# 在业务模块导入前初始化日志，确保 Agent 和模型装配过程的 INFO 日志可见。
configure_application_logging()
