import contextlib
from collections.abc import AsyncIterator
from typing import Any

from app.server.agent.src.checkpoint.config import AgentCheckpointConfig


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
        self._context: Any | None = None

    async def get_checkpointer(self) -> Any:
        """
        获取可传给 LangGraph create_agent(..., checkpointer=...) 的 checkpointer。

        Returns:
            LangGraph checkpointer 实例；当配置为 none 时返回 None。
        """
        if self.config.checkpoint_type in {"", "none", "disabled", "false"}:
            return None

        # 参考 agent_engine 的 CheckpointerManager：checkpointer 是进程级长生命周期对象。
        # 这样可以避免每次请求都创建/销毁数据库连接，也能让 LangGraph 状态持久化保持稳定。
        if self._instance is not None and not self._is_connection_closed(self._instance):
            return self._instance

        self._context = self._make_checkpointer()
        self._instance = await self._context.__aenter__()
        return self._instance

    async def close(self) -> None:
        """
        关闭 checkpointer 底层连接。

        这个方法预留给 FastAPI lifespan 使用；当前服务退出时即使不显式调用，
        进程结束也会释放连接，但后续做优雅停机时可以接入这里。
        """
        if self._context is not None:
            await self._context.__aexit__(None, None, None)
        self._context = None
        self._instance = None

    def _is_connection_closed(self, checkpointer: Any) -> bool:
        """
        判断 checkpointer 底层连接是否已关闭。

        Args:
            checkpointer: LangGraph checkpointer 实例。

        Returns:
            连接已关闭时返回 True，否则返回 False。
        """
        conn = getattr(checkpointer, "conn", None)
        if conn is None:
            return False
        return bool(getattr(conn, "closed", False))

    @contextlib.asynccontextmanager
    async def _make_checkpointer(self) -> AsyncIterator[Any]:
        """
        创建 checkpointer 异步上下文。

        Yields:
            LangGraph checkpointer 实例。
        """
        if self.config.checkpoint_type == "memory":
            try:
                from langgraph.checkpoint.memory import InMemorySaver
            except ImportError as error:
                raise RuntimeError("缺少 LangGraph 依赖，请先安装 langgraph。") from error

            yield InMemorySaver()
            return

        if self.config.checkpoint_type == "postgres":
            try:
                from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
            except ImportError as error:
                raise RuntimeError(
                    "缺少 PostgreSQL Checkpointer 依赖，请先安装 langgraph-checkpoint-postgres 和 psycopg。"
                ) from error

            # AsyncPostgresSaver 使用 psycopg，所以这里必须传标准 postgresql:// 连接串。
            # setup() 会初始化 LangGraph 官方 checkpointer 所需表结构。
            async with AsyncPostgresSaver.from_conn_string(self.config.get_standard_pg_url()) as saver:
                await saver.setup()
                yield saver
            return

        raise RuntimeError(f"不支持的 CHECKPOINTER_TYPE: {self.config.checkpoint_type}")
