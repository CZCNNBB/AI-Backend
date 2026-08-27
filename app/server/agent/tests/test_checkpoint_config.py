import os
import unittest
from unittest.mock import patch

from app.server.agent.src.checkpoint.config import AgentCheckpointConfig


class AgentCheckpointConfigTestCase(unittest.TestCase):
    """验证 Checkpointer 环境变量解析和参数边界。"""

    def test_from_env_uses_pool_defaults(self) -> None:
        """未配置连接池参数时应使用经过容量控制的默认值。"""
        clean_environment = {
            "CHECKPOINTER_TYPE": "postgres",
            "POSTGRES_HOST": "127.0.0.1",
            "POSTGRES_PORT": "5433",
            "POSTGRES_DATABASE": "ai",
            "POSTGRES_USER": "postgres",
            "POSTGRES_PASSWORD": "secret",
            "CHECKPOINTER_POSTGRES_SCHEMA": "agent",
        }
        with patch.dict(os.environ, clean_environment, clear=True):
            config = AgentCheckpointConfig.from_env()

        self.assertEqual(config.pool_min_size, 1)
        self.assertEqual(config.pool_max_size, 5)
        self.assertEqual(config.pool_timeout, 10)
        self.assertEqual(config.pool_startup_timeout, 15)
        self.assertEqual(config.pool_max_idle, 300)
        self.assertEqual(config.pool_max_lifetime, 1800)

    def test_from_env_reads_custom_pool_values(self) -> None:
        """连接池环境变量应完整进入配置对象。"""
        custom_environment = {
            "CHECKPOINTER_TYPE": "postgres",
            "POSTGRES_HOST": "db.internal",
            "POSTGRES_PORT": "5432",
            "POSTGRES_DATABASE": "ai",
            "POSTGRES_USER": "postgres",
            "POSTGRES_PASSWORD": "secret",
            "CHECKPOINTER_POSTGRES_SCHEMA": "agent_checkpoint",
            "POSTGRES_CONNECT_TIMEOUT": "7",
            "CHECKPOINTER_POOL_MIN_SIZE": "2",
            "CHECKPOINTER_POOL_MAX_SIZE": "8",
            "CHECKPOINTER_POOL_TIMEOUT": "12.5",
            "CHECKPOINTER_POOL_STARTUP_TIMEOUT": "20",
            "CHECKPOINTER_POOL_MAX_IDLE": "400",
            "CHECKPOINTER_POOL_MAX_LIFETIME": "2400",
        }
        with patch.dict(os.environ, custom_environment, clear=True):
            config = AgentCheckpointConfig.from_env()

        self.assertEqual(config.connect_timeout, 7)
        self.assertEqual(config.pool_min_size, 2)
        self.assertEqual(config.pool_max_size, 8)
        self.assertEqual(config.pool_timeout, 12.5)
        self.assertEqual(config.pool_startup_timeout, 20)
        self.assertEqual(config.pool_max_idle, 400)
        self.assertEqual(config.pool_max_lifetime, 2400)

    def test_rejects_min_size_greater_than_max_size(self) -> None:
        """最小连接数大于最大连接数时应在启动前失败。"""
        with self.assertRaisesRegex(ValueError, "MIN_SIZE 不能大于"):
            self._make_config(pool_min_size=6, pool_max_size=5)

    def test_rejects_invalid_schema(self) -> None:
        """Schema 中包含 SQL 片段时必须拒绝配置。"""
        with self.assertRaisesRegex(ValueError, "合法 PostgreSQL 标识符"):
            self._make_config(schema="agent,public;drop schema public")

    def test_rejects_legacy_disabled_alias(self) -> None:
        """不再兼容 disabled 等模糊别名，停用时必须明确使用 none。"""
        with self.assertRaisesRegex(ValueError, "只支持 postgres、memory、none"):
            self._make_config(checkpoint_type="disabled")

    @staticmethod
    def _make_config(**overrides: object) -> AgentCheckpointConfig:
        """创建一份合法基础配置，并允许单个测试覆盖目标字段。"""
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


if __name__ == "__main__":
    unittest.main()
