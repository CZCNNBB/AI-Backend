from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session, create_engine

from app.common.config.database_config import POSTGRES_CONFIG, postgres_connection_string


# 创建全局 PostgreSQL 数据库引擎。
# 说明：FastAPI 每个请求会通过 get_postgres_engine 获取独立 Session，底层连接由连接池复用。
engine = create_engine(
    postgres_connection_string,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    # 数据库未启动或网络不可达时快速失败，避免服务启动长期卡住。
    connect_args={"connect_timeout": POSTGRES_CONFIG["connect_timeout"]},
)


def check_postgres_health() -> None:
    """
    检查 PostgreSQL 是否可连接。

    服务启动时会调用该函数；如果连接失败，直接抛出 RuntimeError 阻止服务启动。
    """
    try:
        with Session(engine) as db:
            # select 1 是最小健康检查，只验证数据库连接、账号、密码、库名是否可用。
            db.exec(text("select 1")).one()
    except SQLAlchemyError as error:
        raise RuntimeError(f"PostgreSQL 健康检查失败: {error}") from error
    except UnicodeDecodeError as error:
        # 某些 Windows/PostgreSQL 组合在连接错误信息为中文时可能触发编码异常。
        raise RuntimeError("PostgreSQL 健康检查失败，请检查账号、密码、端口、库名或 pg_hba.conf。") from error


def get_postgres_engine():
    """
    FastAPI 依赖注入使用的数据库 Session 生成器。

    请求结束后，with 语句会自动关闭 Session，避免连接泄露。
    """
    with Session(engine) as db:
        yield db


def get_db_session() -> Session:
    """
    普通函数调用使用的数据库 Session 工厂。

    调用方需要自行关闭 Session，推荐使用 with get_db_session() as db。
    """
    return Session(engine)
