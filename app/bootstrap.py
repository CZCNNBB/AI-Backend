import asyncio
import os

from dotenv import load_dotenv

from app.common.core.logging_config import configure_application_logging


# Windows 下 Playwright 启动浏览器需要创建子进程。
# SelectorEventLoop 不支持 asyncio.create_subprocess_exec，会触发 NotImplementedError；
# ProactorEventLoop 支持子进程，因此浏览器采集模式必须使用它。
if os.name == "nt" and hasattr(asyncio, "WindowsProactorEventLoopPolicy"):
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

# 加载 backend/.env 中的环境变量。
load_dotenv(override=True)

# 在业务模块导入前初始化日志，确保 Agent 和模型装配过程的 INFO 日志可见。
configure_application_logging()
