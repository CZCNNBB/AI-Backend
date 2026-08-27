import asyncio
import unittest
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import patch

from app.server.agent.src.checkpoint.config import AgentCheckpointConfig
from app.server.agent.src.checkpoint.service import (
    CHECKPOINT_SETUP_ADVISORY_LOCK_ID,
    AgentCheckpointService,
    CheckpointServiceState,
)


class FakeAsyncConnection:
    """记录 advisory lock SQL 的异步测试连接。"""

    def __init__(self) -> None:
        """初始化 SQL 调用记录。"""
        self.executed: list[tuple[str, tuple[Any, ...]]] = []

    async def execute(self, sql: str, parameters: tuple[Any, ...]) -> None:
        """记录测试期间执行的 SQL 和参数。"""
        self.executed.append((sql, parameters))


class FakeAsyncConnectionPool:
    """模拟 psycopg 异步连接池，避免单元测试访问真实数据库。"""

    instances: list["FakeAsyncConnectionPool"] = []

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """保存构造参数并创建唯一测试连接。"""
        self.args = args
        self.kwargs = kwargs
        self.connection_instance = FakeAsyncConnection()
        self.open_calls: list[tuple[bool, float]] = []
        self.close_calls: list[float] = []
        self.__class__.instances.append(self)

    async def open(self, wait: bool = False, timeout: float = 30) -> None:
        """记录连接池打开调用。"""
        self.open_calls.append((wait, timeout))

    async def close(self, timeout: float = 5) -> None:
        """记录连接池关闭调用。"""
        self.close_calls.append(timeout)

    @asynccontextmanager
    async def connection(self, timeout: float | None = None):
        """返回固定测试连接，模拟连接借用和归还。"""
        del timeout
        yield self.connection_instance

    def get_stats(self) -> dict[str, int]:
        """返回不包含敏感信息的连接池测试统计。"""
        return {"pool_size": 1}

    @staticmethod
    async def check_connection(connection: Any) -> None:
        """提供与真实连接池一致的健康检查回调签名。"""
        del connection


class FakeAsyncPostgresSaver:
    """记录正式 Saver 和 setup Saver 的创建及迁移次数。"""

    instances: list["FakeAsyncPostgresSaver"] = []
    setup_calls = 0

    def __init__(self, conn: Any) -> None:
        """保存 Saver 绑定的连接或连接池。"""
        self.conn = conn
        self.__class__.instances.append(self)

    async def setup(self) -> None:
        """记录官方表结构迁移调用。"""
        self.__class__.setup_calls += 1


class AgentCheckpointServiceTestCase(unittest.IsolatedAsyncioTestCase):
    """验证 Checkpointer 生命周期、连接池复用和迁移锁。"""

    def setUp(self) -> None:
        """清空 Fake 类的跨测试调用记录。"""
        FakeAsyncConnectionPool.instances.clear()
        FakeAsyncPostgresSaver.instances.clear()
        FakeAsyncPostgresSaver.setup_calls = 0

    async def test_get_checkpointer_requires_startup(self) -> None:
        """未经过 lifespan 初始化时不能在请求中懒创建 Checkpointer。"""
        service = AgentCheckpointService(self._make_config(checkpoint_type="none"))

        with self.assertRaisesRegex(RuntimeError, "尚未在 FastAPI lifespan"):
            await service.get_checkpointer()

    async def test_none_mode_is_ready_and_returns_none(self) -> None:
        """none 模式仍需经过 startup，但不会创建外部资源。"""
        service = AgentCheckpointService(self._make_config(checkpoint_type="none"))

        await service.startup()

        self.assertEqual(service.state, CheckpointServiceState.READY)
        self.assertIsNone(await service.get_checkpointer())
        await service.close()
        self.assertEqual(service.state, CheckpointServiceState.CLOSED)

    async def test_concurrent_startup_creates_only_one_pool(self) -> None:
        """同一进程的并发 startup 调用只能创建一个连接池并迁移一次。"""
        service = AgentCheckpointService(self._make_config())

        with self._patch_postgres_classes():
            await asyncio.gather(service.startup(), service.startup(), service.startup())

        self.assertEqual(len(FakeAsyncConnectionPool.instances), 1)
        self.assertEqual(FakeAsyncPostgresSaver.setup_calls, 1)
        self.assertEqual(service.state, CheckpointServiceState.READY)

    async def test_postgres_startup_binds_formal_saver_to_pool(self) -> None:
        """迁移 Saver 应绑定锁连接，正式 Saver 应绑定应用级连接池。"""
        service = AgentCheckpointService(self._make_config())

        with self._patch_postgres_classes():
            await service.startup()

        pool = FakeAsyncConnectionPool.instances[0]
        self.assertEqual(pool.open_calls, [(True, 15)])
        self.assertEqual(len(FakeAsyncPostgresSaver.instances), 2)
        self.assertIs(FakeAsyncPostgresSaver.instances[0].conn, pool.connection_instance)
        self.assertIs(FakeAsyncPostgresSaver.instances[1].conn, pool)
        self.assertIs(await service.get_checkpointer(), FakeAsyncPostgresSaver.instances[1])

        executed_sql = pool.connection_instance.executed
        self.assertEqual(executed_sql[0][1], (CHECKPOINT_SETUP_ADVISORY_LOCK_ID,))
        self.assertIn("pg_advisory_lock", executed_sql[0][0])
        self.assertIn("pg_advisory_unlock", executed_sql[1][0])

    async def test_close_is_idempotent(self) -> None:
        """多次关闭服务只能关闭一次底层连接池。"""
        service = AgentCheckpointService(self._make_config())
        with self._patch_postgres_classes():
            await service.startup()
            await service.close()
            await service.close()

        pool = FakeAsyncConnectionPool.instances[0]
        self.assertEqual(pool.close_calls, [10])
        self.assertEqual(service.state, CheckpointServiceState.CLOSED)

    @staticmethod
    def _make_config(**overrides: object) -> AgentCheckpointConfig:
        """创建供服务测试使用的合法配置。"""
        values: dict[str, object] = {
            "checkpoint_type": "postgres",
            "host": "127.0.0.1",
            "port": 5433,
            "database": "ai",
            "username": "postgres",
            "password": "secret",
            "schema": "agent",
            "connect_timeout": 5,
            "pool_min_size": 1,
            "pool_max_size": 5,
            "pool_timeout": 10,
            "pool_startup_timeout": 15,
            "pool_max_idle": 300,
            "pool_max_lifetime": 1800,
        }
        values.update(overrides)
        return AgentCheckpointConfig(**values)  # type: ignore[arg-type]

    @staticmethod
    def _patch_postgres_classes():
        """替换运行时延迟导入的 PostgreSQL Saver 与连接池类。"""
        return _CombinedPatch(
            patch(
                "langgraph.checkpoint.postgres.aio.AsyncPostgresSaver",
                FakeAsyncPostgresSaver,
            ),
            patch("psycopg_pool.AsyncConnectionPool", FakeAsyncConnectionPool),
        )


class _CombinedPatch:
    """组合两个 patch 上下文，确保进入和退出顺序清晰可控。"""

    def __init__(self, *patchers: Any) -> None:
        """保存需要组合执行的 patcher。"""
        self.patchers = patchers

    def __enter__(self) -> "_CombinedPatch":
        """按声明顺序启动全部 patch。"""
        for patcher in self.patchers:
            patcher.start()
        return self

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> bool:
        """按相反顺序停止全部 patch，且不吞掉测试异常。"""
        del exc_type, exc_value, traceback
        for patcher in reversed(self.patchers):
            patcher.stop()
        return False


if __name__ == "__main__":
    unittest.main()
