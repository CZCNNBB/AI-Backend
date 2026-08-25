from types import TracebackType

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
    FastAPI 依赖注入使用的请求级数据库事务。

    接口正常返回时统一提交，接口抛出异常时统一回滚，最后必定关闭 Session。
    Repository 只负责执行 SQL 和 flush，不再自行决定事务提交边界。
    """
    with Session(engine) as db:
        try:
            yield db
            # HTTP 接口已顺利完成，由请求边界统一提交本次业务修改。
            db.commit()
        except Exception:
            # 任意业务步骤失败时整体回滚，避免留下只完成一部分的数据。
            db.rollback()
            raise


def get_db_session() -> Session:
    """
    普通函数调用使用的数据库 Session 工厂。

    调用方需要自行关闭 Session，推荐使用 with get_db_session() as db。
    """
    return Session(engine)


class PostgresTransaction:
    """边界清晰、退出时必定关闭 Session 的 PostgreSQL 短事务。"""

    def __init__(self) -> None:
        """初始化短事务对象，暂不向连接池申请真实数据库连接。"""
        # SQLAlchemy Session 采用延迟取连接机制：创建 Session 对象时不会立刻连接数据库，
        # 第一次执行 SQL 时才会从连接池借用连接。
        self.db = Session(engine)

    def __enter__(self) -> Session:
        """进入短事务并返回业务代码使用的 Session。"""
        return self.db

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        """根据执行结果提交或回滚，并无条件关闭 Session。

        Args:
            exc_type: with 块抛出的异常类型；正常结束时为空。
            exc_value: with 块抛出的异常对象；正常结束时为空。
            traceback: with 块异常的调用栈；正常结束时为空。

        Returns:
            固定返回 False，不吞掉业务异常。
        """
        try:
            if exc_type is None:
                # Repository 只负责 flush；短事务正常结束后在此统一提交。
                self.db.commit()
            else:
                self.db.rollback()
        finally:
            # 无论 commit、rollback 或业务代码是否失败，都必须把连接归还连接池。
            self.db.close()
        return False


def postgres_transaction() -> PostgresTransaction:
    """创建一个可供 ``with`` 使用的 PostgreSQL 短事务。

    Returns:
        新的短事务上下文对象。每次调用都返回独立 Session，不能跨阶段复用。

    该工厂用于 Agent 流式运行的开始、成功、失败和中断落库阶段。
    调用方离开 ``with`` 块后，Session 一定关闭，不会跟随 LLM、MCP 或 SSE 长期存活。
    """
    return PostgresTransaction()
