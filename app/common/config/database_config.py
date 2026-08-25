import os

from dotenv import load_dotenv
from sqlalchemy.engine import URL


# 允许数据库配置在独立脚本、测试脚本、FastAPI 启动流程中都能读取 backend/.env。
load_dotenv(override=True)


def env_int(name: str, default: int) -> int:
    """
    读取整数环境变量，缺失或格式错误时返回默认值。

    Args:
        name: 环境变量名称。
        default: 默认整数值。
    """
    value = os.getenv(name)
    if value is None or value == "":
        return default
    try:
        return int(value)
    except ValueError:
        return default


# PostgreSQL 配置。
# 当前服务的岗位库、爬虫运行记录、原始岗位数据都使用这个连接。
POSTGRES_CONFIG = {
    "host": os.getenv("POSTGRES_HOST", "127.0.0.1"),
    "port": env_int("POSTGRES_PORT", 5432),
    "username": os.getenv("POSTGRES_USER", ""),
    "password": os.getenv("POSTGRES_PASSWORD", ""),
    "database": os.getenv("POSTGRES_DATABASE", "career_ai"),
    "connect_timeout": env_int("POSTGRES_CONNECT_TIMEOUT", 5),
}

postgres_connection_string = URL.create(
    "postgresql+psycopg",
    username=POSTGRES_CONFIG["username"],
    password=POSTGRES_CONFIG["password"],
    host=POSTGRES_CONFIG["host"],
    port=POSTGRES_CONFIG["port"],
    database=POSTGRES_CONFIG["database"],
)
