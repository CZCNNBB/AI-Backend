import unittest
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI

from app.common.core.lifespan import app_lifespan


class CheckpointLifespanTestCase(unittest.IsolatedAsyncioTestCase):
    """验证 Checkpointer 与 Knowledge 基础设施的启动和清理顺序。"""

    async def test_lifespan_starts_checkpoint_before_knowledge(self) -> None:
        """应用必须先准备 Checkpointer，再启动 Knowledge，并按相反顺序关闭。"""
        events: list[str] = []

        async def checkpoint_startup() -> None:
            """记录 Checkpointer 启动事件。"""
            events.append("checkpoint_startup")

        async def checkpoint_close() -> None:
            """记录 Checkpointer 关闭事件。"""
            events.append("checkpoint_close")

        async def knowledge_startup() -> None:
            """记录 Knowledge 启动事件。"""
            events.append("knowledge_startup")

        async def knowledge_close() -> None:
            """记录 Knowledge 关闭事件。"""
            events.append("knowledge_close")

        with (
            patch(
                "app.common.core.lifespan.agent_checkpoint_service.startup",
                side_effect=checkpoint_startup,
            ),
            patch(
                "app.common.core.lifespan.agent_checkpoint_service.close",
                side_effect=checkpoint_close,
            ),
            patch(
                "app.common.core.lifespan.knowledge_service.startup",
                side_effect=knowledge_startup,
            ),
            patch(
                "app.common.core.lifespan.knowledge_service.close",
                side_effect=knowledge_close,
            ),
        ):
            async with app_lifespan(FastAPI()):
                events.append("application_running")

        self.assertEqual(
            events,
            [
                "checkpoint_startup",
                "knowledge_startup",
                "application_running",
                "knowledge_close",
                "checkpoint_close",
            ],
        )

    async def test_lifespan_cleans_resources_when_knowledge_startup_fails(self) -> None:
        """Knowledge 启动失败时也必须清理两个基础设施服务。"""
        checkpoint_startup = AsyncMock()
        checkpoint_close = AsyncMock()
        knowledge_startup = AsyncMock(side_effect=RuntimeError("knowledge failed"))
        knowledge_close = AsyncMock()

        with (
            patch(
                "app.common.core.lifespan.agent_checkpoint_service.startup",
                checkpoint_startup,
            ),
            patch(
                "app.common.core.lifespan.agent_checkpoint_service.close",
                checkpoint_close,
            ),
            patch(
                "app.common.core.lifespan.knowledge_service.startup",
                knowledge_startup,
            ),
            patch(
                "app.common.core.lifespan.knowledge_service.close",
                knowledge_close,
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "knowledge failed"):
                async with app_lifespan(FastAPI()):
                    self.fail("Knowledge 启动失败后不应进入应用运行阶段")

        checkpoint_startup.assert_awaited_once()
        knowledge_startup.assert_awaited_once()
        knowledge_close.assert_awaited_once()
        checkpoint_close.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
