import asyncio
import logging
from enum import Enum
from typing import Any

from app.server.agent.src.checkpoint.config import AgentCheckpointConfig


logger = logging.getLogger("ai_backend.agent.checkpoint")

# 所有 AI-backend Worker 使用同一个 advisory lock 编号，串行执行 LangGraph 表迁移。
CHECKPOINT_SETUP_ADVISORY_LOCK_ID = 4_120_262_001


class CheckpointServiceState(str, Enum):
    """Checkpointer 服务的应用生命周期状态。"""

    NEW = "new"
    STARTING = "starting"
    READY = "ready"
    CLOSING = "closing"
    CLOSED = "closed"


class AgentCheckpointService:
    """Agent Checkpointer 服务，负责创建和复用 LangGraph 状态持久化实例。"""

    def __init__(self, config: AgentCheckpointConfig | None = None):
        """
        初始化 Agent Checkpointer 服务。

        Args:
            config: Checkpointer 配置；不传时从环境变量读取。
        """
        self.config = config or AgentCheckpointConfig.from_env()
        self._instance: Any | None = None
        self._pool: Any | None = None
        self._initialization_lock = asyncio.Lock()
        self._state = CheckpointServiceState.NEW

    @property
    def state(self) -> CheckpointServiceState:
        """返回当前 Checkpointer 生命周期状态，供健康检查和测试使用。"""
        return self._state

    async def startup(self) -> None:
        """在应用启动阶段初始化 Checkpointer 及其底层连接池。"""
        async with self._initialization_lock:
            if self._state == CheckpointServiceState.READY:
                return
            if self._state in {
                CheckpointServiceState.STARTING,
                CheckpointServiceState.CLOSING,
            }:
                raise RuntimeError(f"Checkpointer 当前状态不允许启动: {self._state.value}")

            self._state = CheckpointServiceState.STARTING
            logger.info("Checkpointer 初始化开始: type=%s", self.config.checkpoint_type)
            try:
                if self.config.checkpoint_type == "none":
                    self._instance = None
                elif self.config.checkpoint_type == "memory":
                    self._instance = self._create_memory_saver()
                else:
                    await self._startup_postgres()
            except Exception:
                # 初始化任一阶段失败都要释放已经打开的池，不能留下半初始化资源。
                await self._close_pool_safely()
                self._instance = None
                self._state = CheckpointServiceState.CLOSED
                logger.exception(
                    "Checkpointer 初始化失败: type=%s",
                    self.config.checkpoint_type,
                )
                raise

            self._state = CheckpointServiceState.READY
            logger.info("Checkpointer 初始化完成: type=%s", self.config.checkpoint_type)

    async def get_checkpointer(self) -> Any:
        """
        获取可传给 LangGraph create_agent(..., checkpointer=...) 的 checkpointer。

        Returns:
            LangGraph checkpointer 实例；当配置为 none 时返回 None。
        """
        if self._state != CheckpointServiceState.READY:
            raise RuntimeError(
                "Checkpointer 尚未在 FastAPI lifespan 中完成初始化: "
                f"state={self._state.value}"
            )
        return self._instance

    async def close(self) -> None:
        """
        关闭 checkpointer 底层连接。

        该方法由 FastAPI lifespan 调用，并保持幂等。
        """
        async with self._initialization_lock:
            if self._state in {
                CheckpointServiceState.NEW,
                CheckpointServiceState.CLOSED,
            }:
                return

            self._state = CheckpointServiceState.CLOSING
            logger.info("Checkpointer 关闭开始: type=%s", self.config.checkpoint_type)
            self._instance = None
            await self._close_pool_safely()
            self._state = CheckpointServiceState.CLOSED
            logger.info("Checkpointer 关闭完成: type=%s", self.config.checkpoint_type)

    @staticmethod
    def _create_memory_saver() -> Any:
        """创建进程级内存 Checkpointer。"""
        try:
            from langgraph.checkpoint.memory import InMemorySaver
        except ImportError as error:
            raise RuntimeError("缺少 LangGraph 依赖，请先安装 langgraph。") from error
        return InMemorySaver()

    async def _startup_postgres(self) -> None:
        """打开 PostgreSQL 异步连接池并完成 LangGraph Checkpoint 表迁移。"""
        try:
            from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
            from psycopg.rows import dict_row
            from psycopg_pool import AsyncConnectionPool
        except ImportError as error:
            raise RuntimeError(
                "缺少 PostgreSQL Checkpointer 依赖，请先安装 "
                "langgraph-checkpoint-postgres、psycopg 和 psycopg-pool。"
            ) from error

        logger.info(
            "Checkpointer PostgreSQL 初始化中: host=%s port=%s database=%s schema=%s",
            self.config.host,
            self.config.port,
            self.config.database,
            self.config.schema,
        )
        pool = AsyncConnectionPool(
            conninfo=self.config.get_standard_pg_url(),
            min_size=self.config.pool_min_size,
            max_size=self.config.pool_max_size,
            timeout=self.config.pool_timeout,
            max_idle=self.config.pool_max_idle,
            max_lifetime=self.config.pool_max_lifetime,
            open=False,
            kwargs={
                "autocommit": True,
                "prepare_threshold": 0,
                "row_factory": dict_row,
                "connect_timeout": self.config.connect_timeout,
            },
            check=AsyncConnectionPool.check_connection,
            name="agent-checkpointer",
        )
        self._pool = pool
        await pool.open(
            wait=True,
            timeout=self.config.pool_startup_timeout,
        )
        logger.info(
            "Checkpointer 异步连接池已打开: min_size=%s max_size=%s",
            self.config.pool_min_size,
            self.config.pool_max_size,
        )

        await self._setup_postgres_saver(pool, AsyncPostgresSaver)
        self._instance = AsyncPostgresSaver(conn=pool)
        logger.info("Checkpointer PostgreSQL Saver 已就绪: stats=%s", pool.get_stats())

    async def _setup_postgres_saver(self, pool: Any, saver_class: Any) -> None:
        """在跨进程 advisory lock 内串行执行 LangGraph 官方迁移。"""
        logger.info("Checkpointer 数据表检查开始")
        async with pool.connection(timeout=self.config.pool_timeout) as connection:
            await connection.execute(
                "SELECT pg_advisory_lock(%s)",
                (CHECKPOINT_SETUP_ADVISORY_LOCK_ID,),
            )
            try:
                # setup() 绑定持锁连接，避免 max_size=1 时再次借连接造成自我等待。
                setup_saver = saver_class(conn=connection)
                await setup_saver.setup()
            finally:
                await connection.execute(
                    "SELECT pg_advisory_unlock(%s)",
                    (CHECKPOINT_SETUP_ADVISORY_LOCK_ID,),
                )
        logger.info("Checkpointer 数据表检查完成")

    async def _close_pool_safely(self) -> None:
        """关闭已经创建的连接池；关闭失败时记录日志并继续清理引用。"""
        pool = self._pool
        self._pool = None
        if pool is None:
            return
        try:
            await pool.close(timeout=self.config.pool_timeout)
        except Exception:  # noqa: BLE001
            logger.exception("Checkpointer 连接池关闭失败")


# 生产 API 与 FastAPI lifespan 必须共享同一个实例，避免一个 Worker 内重复创建连接池。
agent_checkpoint_service = AgentCheckpointService()
