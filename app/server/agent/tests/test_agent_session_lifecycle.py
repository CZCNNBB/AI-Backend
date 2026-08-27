"""Agent 长耗时执行的数据库 Session 生命周期测试。"""

import unittest
from contextlib import AbstractContextManager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.common.db.postgres_db import PostgresTransaction, get_postgres_engine
from app.server.agent.src.agent.resume_service import AgentResumeService
from app.server.agent.src.agent.service import AgentService
from app.server.agent.src.context.repository import AgentContextRepository
from app.server.agent.src.mcp.service import AgentMCPRuntimeService
from app.server.agent.src.runtime.context import AgentRuntimeContext
from app.server.agent.src.schemas.request import AgentResumeRequest, AgentRunRequest, ModelRuntimeOptions
from app.server.fastmcp.src.models import MCPToolRecord
from app.server.fastmcp.src.schemas import MCPToolUpsertRequest, MCPToolView
from app.server.fastmcp.src.service import MCPToolService


class FakeSession:
    """记录测试事务是否仍处于打开状态。"""

    def __init__(self, sequence: int):
        """初始化测试 Session。

        Args:
            sequence: 本次创建的事务序号。
        """
        self.sequence = sequence
        self.active = False


class FakeTransaction(AbstractContextManager):
    """模拟 postgres_transaction，并记录进入和退出时机。"""

    def __init__(self, sessions: list[FakeSession]):
        """创建一个新的测试短事务。

        Args:
            sessions: 保存全部测试 Session 的共享列表。
        """
        self.sessions = sessions
        self.session = FakeSession(len(sessions) + 1)
        sessions.append(self.session)

    def __enter__(self) -> FakeSession:
        """标记测试 Session 已打开并返回它。"""
        self.session.active = True
        return self.session

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        """标记测试 Session 已关闭，并保持原异常传播语义。"""
        self.session.active = False
        return False


class FakeStreamingAgent:
    """模拟 LangGraph Agent，并在模型执行前检查开始 Session 已关闭。"""

    def __init__(self, sessions: list[FakeSession]):
        """保存事务状态列表，供 astream 执行时断言。

        Args:
            sessions: 已创建的测试 Session 列表。
        """
        self.sessions = sessions

    async def astream(self, *args, **kwargs):
        """产出一个模型分片，并验证长耗时阶段没有活跃业务 Session。"""
        if not self.sessions:
            raise AssertionError("模型执行前应至少创建一个开始事务")
        if any(session.active for session in self.sessions):
            raise AssertionError("模型流式执行期间不应持有业务数据库 Session")
        yield "messages", object()


class AgentSessionLifecycleTestCase(unittest.IsolatedAsyncioTestCase):
    """验证正式 Agent 流式运行使用开始和结束两个独立短事务。"""

    async def test_stream_closes_start_session_before_model_execution(self) -> None:
        """开始事务应在首个模型分片前关闭，结束落库应使用新事务。"""
        sessions: list[FakeSession] = []
        context = AgentRuntimeContext(
            run_id="run-short-session",
            thread_id="conversation-short-session",
            query="测试短事务",
        )
        request = AgentRunRequest(
            query="测试短事务",
            conversation_id=context.thread_id,
            stream=True,
            runtime_options=ModelRuntimeOptions(model_code="chat-main"),
        )

        lifecycle_service = MagicMock()
        lifecycle_service.resolve_template_request.return_value = request
        lifecycle_service.prepare_run_context.return_value = (context, True, True)

        async def assert_final_transaction(*args, **kwargs) -> None:
            """验证结束落库发生在第二个、仍处于打开状态的短事务中。"""
            self.assertEqual(len(sessions), 2)
            self.assertFalse(sessions[0].active)
            self.assertTrue(sessions[1].active)
            self.assertIs(args[4], sessions[1])

        lifecycle_service.finalize_run = AsyncMock(side_effect=assert_final_transaction)

        async def assemble_after_start_closed(*args, **kwargs):
            """验证 Agent 组装开始前，业务开始事务已经关闭。"""
            self.assertEqual(len(sessions), 1)
            self.assertFalse(sessions[0].active)
            return SimpleNamespace(
                agent=FakeStreamingAgent(sessions),
                metadata={"model_code": "chat-main"},
            )

        assembler = MagicMock()
        assembler.assemble = AsyncMock(side_effect=assemble_after_start_closed)

        stream_parser = MagicMock()
        stream_parser.normalize_message_stream_chunk.return_value = [
            {"type": "model_delta", "data": {"content": "完成"}}
        ]

        service = AgentService.__new__(AgentService)
        service.lifecycle_service = lifecycle_service
        service.assembler = assembler
        service.stream_parser = stream_parser
        service.context_service = MagicMock()
        service.run_service = MagicMock()

        def build_transaction() -> FakeTransaction:
            """为每个生命周期阶段创建一个新的测试事务。"""
            return FakeTransaction(sessions)

        with patch(
            "app.server.agent.src.agent.service.postgres_transaction",
            side_effect=build_transaction,
        ):
            events = [
                event
                async for event in service.stream(
                    request,
                    persist_business_records=True,
                )
            ]

        self.assertEqual(
            [event["type"] for event in events],
            ["run_start", "agent_assembled", "model_delta", "run_end"],
        )
        self.assertEqual(events[0]["data"]["conversation_id"], context.thread_id)
        self.assertEqual(len(sessions), 2)
        self.assertTrue(all(not session.active for session in sessions))
        lifecycle_service.finalize_run.assert_awaited_once()

    async def test_resume_stream_closes_start_session_before_model_execution(self) -> None:
        """中断恢复也应在模型继续执行前关闭读取原运行记录的 Session。"""
        sessions: list[FakeSession] = []
        context = AgentRuntimeContext(
            run_id="run-resume-short-session",
            thread_id="conversation-resume-short-session",
            checkpoint_thread_id="platform:1:user:user-1:conversation:conversation-resume-short-session",
            platform_id=1,
            external_user_id="user-1",
            query="继续执行",
        )
        resume_request = AgentResumeRequest(
            run_id=context.run_id,
            conversation_id=context.thread_id,
            thread_id=context.checkpoint_thread_id,
            platform_id=1,
            external_user_id="user-1",
            resume_value={"type": "approval", "data": {"approved": True}},
            stream=True,
        )
        run_request = AgentRunRequest(
            query=context.query,
            conversation_id=context.thread_id,
            stream=True,
            runtime_options=ModelRuntimeOptions(model_code="chat-main"),
        )
        run_row = SimpleNamespace(
            run_id=context.run_id,
            conversation_id=context.thread_id,
            query=context.query,
            status="interrupted",
            extra_metadata={},
        )

        async def assemble_resume_after_start_closed(*args, **kwargs):
            """验证恢复 Agent 重新组装前，原运行读取事务已经关闭。"""
            self.assertEqual(len(sessions), 1)
            self.assertFalse(sessions[0].active)
            return SimpleNamespace(
                agent=FakeStreamingAgent(sessions),
                metadata={"model_code": "chat-main"},
            )

        assembler = MagicMock()
        assembler.assemble = AsyncMock(side_effect=assemble_resume_after_start_closed)
        stream_parser = MagicMock()
        stream_parser.normalize_message_stream_chunk.return_value = [
            {"type": "model_delta", "data": {"content": "已恢复"}}
        ]

        service = AgentResumeService(
            assembler=assembler,
            memory_service=MagicMock(),
            context_service=MagicMock(),
            run_service=MagicMock(),
            stream_parser=stream_parser,
        )
        service._get_interrupted_run = MagicMock(return_value=run_row)
        service._build_resume_request_from_run = MagicMock(return_value=run_request)
        service._build_resume_context = MagicMock(return_value=context)

        async def assert_resume_final_transaction(*args, **kwargs) -> None:
            """验证恢复成功落库使用第二个独立短事务。"""
            self.assertEqual(len(sessions), 2)
            self.assertFalse(sessions[0].active)
            self.assertTrue(sessions[1].active)
            self.assertIs(kwargs["db"], sessions[1])

        service._finalize_resume_run = AsyncMock(side_effect=assert_resume_final_transaction)

        def build_transaction() -> FakeTransaction:
            """为恢复开始和结束阶段分别创建测试事务。"""
            return FakeTransaction(sessions)

        with patch(
            "app.server.agent.src.agent.resume_service.postgres_transaction",
            side_effect=build_transaction,
        ):
            events = [event async for event in service.resume_stream(resume_request)]

        self.assertEqual(
            [event["type"] for event in events],
            ["resume_start", "agent_assembled", "model_delta", "run_end"],
        )
        self.assertEqual(events[0]["data"]["conversation_id"], context.thread_id)
        self.assertEqual(len(sessions), 2)
        self.assertTrue(all(not session.active for session in sessions))
        service._finalize_resume_run.assert_awaited_once()

    async def test_mcp_remote_discovery_uses_detached_config_snapshot(self) -> None:
        """远程 MCP 工具发现应在配置查询事务关闭后执行。"""
        sessions: list[FakeSession] = []
        record = SimpleNamespace(name="job_search")
        snapshot = MCPToolView(
            name="job_search",
            api_url="http://127.0.0.1:8080/api/jobs/search",
            http_method="POST",
            auth_type="none",
            timeout_seconds=30,
            status="enabled",
        )
        loaded_tool = SimpleNamespace(name="job_search")

        catalog_service = MCPToolService(repository=MagicMock())
        catalog_service._get_enabled_tool_records = MagicMock(return_value=[record])
        catalog_service.to_tool_view = MagicMock(return_value=snapshot)
        service = AgentMCPRuntimeService(catalog_service=catalog_service)

        async def load_after_config_transaction_closed(records, tool_names):
            """验证访问远程 MCP 前配置查询 Session 已经关闭。"""
            self.assertEqual(records, [snapshot])
            self.assertEqual(tool_names, ["job_search"])
            self.assertEqual(len(sessions), 1)
            self.assertFalse(sessions[0].active)
            return [loaded_tool]

        service._load_langchain_tools_from_snapshots = AsyncMock(
            side_effect=load_after_config_transaction_closed
        )

        def build_transaction() -> FakeTransaction:
            """为 MCP 配置查询创建测试短事务。"""
            return FakeTransaction(sessions)

        with patch(
            "app.server.fastmcp.src.service.postgres_transaction",
            side_effect=build_transaction,
        ):
            tools = await service.load_runtime_langchain_tools(["job_search"])

        self.assertEqual(tools, [loaded_tool])
        self.assertEqual(len(sessions), 1)
        self.assertFalse(sessions[0].active)

    def test_postgres_transaction_commits_and_closes_on_success(self) -> None:
        """短事务正常结束时必须提交并关闭 Session。"""
        db = MagicMock()
        with patch("app.common.db.postgres_db.Session", return_value=db):
            with PostgresTransaction() as active_db:
                self.assertIs(active_db, db)

        db.commit.assert_called_once_with()
        db.rollback.assert_not_called()
        db.close.assert_called_once_with()

    def test_postgres_transaction_rolls_back_and_closes_on_failure(self) -> None:
        """短事务发生异常时必须回滚、关闭 Session，并继续抛出原异常。"""
        db = MagicMock()
        with patch("app.common.db.postgres_db.Session", return_value=db):
            with self.assertRaisesRegex(RuntimeError, "事务测试异常"):
                with PostgresTransaction():
                    raise RuntimeError("事务测试异常")

        db.commit.assert_not_called()
        db.rollback.assert_called_once_with()
        db.close.assert_called_once_with()

    def test_request_transaction_commits_after_endpoint_success(self) -> None:
        """FastAPI 请求依赖应在接口正常结束后统一提交并关闭 Session。"""
        db = MagicMock()
        session_context = MagicMock()
        session_context.__enter__.return_value = db

        with patch("app.common.db.postgres_db.Session", return_value=session_context):
            dependency = get_postgres_engine()
            active_db = next(dependency)
            self.assertIs(active_db, db)

            with self.assertRaises(StopIteration):
                next(dependency)

        db.commit.assert_called_once_with()
        db.rollback.assert_not_called()
        session_context.__exit__.assert_called_once()

    def test_request_transaction_rolls_back_after_endpoint_failure(self) -> None:
        """FastAPI 请求依赖应在接口异常时统一回滚并保持原异常传播。"""
        db = MagicMock()
        session_context = MagicMock()
        session_context.__enter__.return_value = db

        with patch("app.common.db.postgres_db.Session", return_value=session_context):
            dependency = get_postgres_engine()
            next(dependency)

            with self.assertRaisesRegex(RuntimeError, "接口事务测试异常"):
                dependency.throw(RuntimeError("接口事务测试异常"))

        db.commit.assert_not_called()
        db.rollback.assert_called_once_with()
        session_context.__exit__.assert_called_once()

    def test_repository_flushes_without_committing(self) -> None:
        """Repository 写操作只能 flush，不能越过 Service 边界自行提交。"""
        db = MagicMock()
        conversation = SimpleNamespace()

        repository = AgentContextRepository()
        saved = repository.create_conversation(db, conversation)

        self.assertIs(saved, conversation)
        db.add.assert_called_once_with(conversation)
        db.flush.assert_called_once_with()
        db.refresh.assert_called_once_with(conversation)
        db.commit.assert_not_called()

    def test_mcp_tool_uses_name_as_only_identity(self) -> None:
        """MCP 工具模型和接口应只使用 name，并指向独立的 mcp Schema。"""
        self.assertEqual(MCPToolRecord.__table__.schema, "mcp")
        self.assertEqual(MCPToolRecord.__table__.name, "mcp_tools")
        self.assertNotIn("mcp_code", MCPToolRecord.__table__.columns)
        self.assertNotIn("mcp_code", MCPToolUpsertRequest.model_fields)
        self.assertNotIn("mcp_code", MCPToolView.model_fields)
        self.assertNotIn("base_url", MCPToolRecord.__table__.columns)
        self.assertIn("api_url", MCPToolRecord.__table__.columns)
        self.assertIn("parameters", MCPToolRecord.__table__.columns)

        request = MCPToolUpsertRequest(
            name=" job_search ",
            platform_ids=[1],
            api_url=" http://127.0.0.1:8080/api/jobs/search ",
        )
        self.assertEqual(request.name, "job_search")
        self.assertEqual(request.api_url, "http://127.0.0.1:8080/api/jobs/search")


if __name__ == "__main__":
    unittest.main()
