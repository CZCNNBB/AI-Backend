import logging
import os


DEFAULT_LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"


def configure_application_logging() -> None:
    """
    初始化 AI-backend 应用日志。

    日志级别通过 LOG_LEVEL 控制，默认使用 INFO。该配置同时支持
    Uvicorn 启动和直接执行脚本，Agent 子日志器会继承统一格式。
    """
    level_name = os.getenv("LOG_LEVEL", "INFO").strip().upper()
    level = getattr(logging, level_name, logging.INFO)

    # basicConfig 仅在根日志器尚未配置时创建处理器，避免覆盖 Uvicorn 自己的日志配置。
    logging.basicConfig(level=level, format=DEFAULT_LOG_FORMAT)

    # 显式设置项目日志器级别，保证 Uvicorn 调整根日志器后 Agent INFO 日志仍然可见。
    logging.getLogger("ai_backend").setLevel(level)
