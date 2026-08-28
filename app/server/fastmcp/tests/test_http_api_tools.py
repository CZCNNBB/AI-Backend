import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
from fastmcp import Client, FastMCP
from pydantic import ValidationError

from app.common.core.exceptions import BusinessException
from app.server.fastmcp.src.executor import (
    HTTPAPIToolExecutor,
    HTTPToolExecutionError,
    HTTPToolExecutionResult,
)
from app.server.fastmcp.src.registry import FastMCPToolRegistry
from app.server.fastmcp.src.schemas import MCPToolPublishRequest, MCPToolUpsertRequest, MCPToolView
from app.server.fastmcp.src.service import MCPToolService


class MCPToolAvailabilityGuardTestCase(unittest.TestCase):
    """验证所有让 MCP Tool 不可用的入口都会执行 Agent 引用保护。"""

    def test_publish_endpoint_checks_agent_references_before_disabling(self) -> None:
        """单独的停用操作必须先校验 Agent 引用，冲突时不能更新数据库状态。"""
        repository = MagicMock()
        repository.get_tool_by_name.return_value = MagicMock(name="query_order", status="enabled")
        platform_service = MagicMock()
        platform_service.validate_tools_can_be_disabled.side_effect = BusinessException(
            code=409,
            msg="工具仍被 Agent 使用",
        )
        service = MCPToolService(
            repository=repository,
            registry=MagicMock(),
            platform_service=platform_service,
        )

        with self.assertRaises(BusinessException):
            service.publish_tool(
                MagicMock(),
                MCPToolPublishRequest(name="query_order", enabled=False),
            )

        platform_service.validate_tools_can_be_disabled.assert_called_once()
        repository.update_status.assert_not_called()

    def test_upsert_checks_agent_references_when_saving_disabled_status(self) -> None:
        """编辑保存为停用状态也必须执行相同校验，不能绕过 publish 接口。"""
        repository = MagicMock()
        platform_service = MagicMock()
        platform_service.validate_tools_can_be_disabled.side_effect = BusinessException(
            code=409,
            msg="工具仍被 Agent 使用",
        )
        service = MCPToolService(
            repository=repository,
            registry=MagicMock(),
            platform_service=platform_service,
        )
        request = MCPToolUpsertRequest(
            name="query_order",
            platform_ids=[1],
            api_url="http://business.test/orders",
            status="disabled",
        )

        with self.assertRaises(BusinessException):
            service.upsert_tool(MagicMock(), request)

        platform_service.validate_tools_can_be_disabled.assert_called_once()
        repository.upsert_tool.assert_not_called()


class HTTPAPIToolExecutorTestCase(unittest.IsolatedAsyncioTestCase):
    """验证参数映射、请求头和认证不会依赖单工具 Python 代码。"""

    async def test_execute_maps_all_parameter_sources_and_locations(self) -> None:
        """tool/runtime/static 参数应正确进入 path、query、header 和 JSON body。"""
        request = MCPToolUpsertRequest(
            name="get_job",
            platform_ids=[1],
            api_url="http://business.test/jobs/{job_id}",
            http_method="POST",
            static_headers={"X-App-Id": "ai-platform", "Authorization": "Bearer secret-token"},
            parameters=[
                {"name": "job_id", "location": "path", "source": "tool", "required": True},
                {"name": "page", "location": "query", "source": "tool", "data_type": "integer", "default": 1},
                {
                    "name": "X-Tenant-Id",
                    "location": "header",
                    "source": "runtime",
                    "runtime_path": "tenant.id",
                    "required": True,
                },
                {"name": "filters.keyword", "location": "body", "source": "tool"},
                {"name": "channel", "location": "body", "source": "static", "value": "agent"},
            ],
        )
        tool_view = MCPToolView(
            **request.model_dump(),
            input_schema=request.build_input_schema(),
        )
        captured_request: dict = {}

        async def capture_request(_client, **request_kwargs):
            """捕获统一执行器最终传给 httpx 的请求配置。"""
            captured_request.update(request_kwargs)
            return httpx.Response(
                status_code=200,
                json={"ok": True},
                request=httpx.Request(request_kwargs["method"], request_kwargs["url"]),
            )

        with patch.object(httpx.AsyncClient, "request", new=capture_request):
            result = await HTTPAPIToolExecutor().execute(
                tool_view,
                {"job_id": "job/001", "filters.keyword": "Python"},
                runtime_inputs={"tenant": {"id": "tenant-1"}},
            )

        self.assertEqual(result.data, {"ok": True})
        self.assertEqual(captured_request["url"], "http://business.test/jobs/job%2F001")
        self.assertEqual(captured_request["params"], {"page": 1})
        self.assertEqual(captured_request["json"], {"filters": {"keyword": "Python"}, "channel": "agent"})
        self.assertEqual(captured_request["headers"]["X-App-Id"], "ai-platform")
        self.assertEqual(captured_request["headers"]["X-Tenant-Id"], "tenant-1")
        self.assertEqual(captured_request["headers"]["Authorization"], "Bearer secret-token")

    async def test_runtime_and_static_parameters_are_hidden_from_input_schema(self) -> None:
        """只有 source=tool 的字段可以出现在模型可见的 MCP 输入 Schema。"""
        request = MCPToolUpsertRequest(
            name="search_jobs",
            platform_ids=[1],
            api_url="http://business.test/jobs",
            parameters=[
                {"name": "keyword", "location": "query", "source": "tool", "required": True},
                {"name": "tenant_id", "location": "header", "source": "runtime"},
                {"name": "app_id", "location": "header", "source": "static", "value": "ai"},
            ],
        )

        input_schema = request.build_input_schema()

        self.assertEqual(list(input_schema["properties"]), ["keyword"])
        self.assertEqual(input_schema["required"], ["keyword"])

    async def test_static_parameter_value_must_match_declared_type(self) -> None:
        """object、boolean 等固定值不能以看似 JSON 的普通字符串混入请求。"""
        valid_request = MCPToolUpsertRequest(
            name="deepseek_test",
            platform_ids=[1],
            api_url="http://business.test/chat/completions",
            parameters=[
                {
                    "name": "thinking",
                    "location": "body",
                    "source": "static",
                    "data_type": "object",
                    "value": {"type": "enabled"},
                },
                {
                    "name": "stream",
                    "location": "body",
                    "source": "static",
                    "data_type": "boolean",
                    "value": False,
                },
            ],
        )
        self.assertEqual(valid_request.parameters[0].value, {"type": "enabled"})
        self.assertIs(valid_request.parameters[1].value, False)

        with self.assertRaises(ValidationError):
            MCPToolUpsertRequest(
                name="invalid_static_object",
                platform_ids=[1],
                api_url="http://business.test/chat/completions",
                parameters=[
                    {
                        "name": "thinking",
                        "location": "body",
                        "source": "static",
                        "data_type": "object",
                        "value": '{"type":"enabled"}',
                    }
                ],
            )

    async def test_business_token_uses_configured_header_verbatim(self) -> None:
        """业务凭证应使用 Tool 配置的目标请求头，并保持值完全不变。"""
        request = MCPToolUpsertRequest(
            name="query_order",
            platform_ids=[1],
            api_url="http://business.test/orders",
            business_token_header="X-Token",
        )
        tool_view = MCPToolView(**request.model_dump(), input_schema=request.build_input_schema())
        captured_request: dict = {}

        async def capture_request(_client, **request_kwargs):
            """捕获执行器最终发送给业务 API 的请求头。"""
            captured_request.update(request_kwargs)
            return httpx.Response(
                status_code=200,
                json={"ok": True},
                request=httpx.Request(request_kwargs["method"], request_kwargs["url"]),
            )

        with patch.object(httpx.AsyncClient, "request", new=capture_request):
            await HTTPAPIToolExecutor().execute(
                tool_view,
                {},
                runtime_credentials={"business_token": "current-user-token"},
            )

        self.assertEqual(
            captured_request["headers"]["X-Token"],
            "current-user-token",
        )

    async def test_business_token_rejects_missing_runtime_credentials(self) -> None:
        """Tool 配置目标请求头后，缺少用户凭证时必须在 HTTP 请求前失败。"""
        request = MCPToolUpsertRequest(
            name="query_order",
            platform_ids=[1],
            api_url="http://business.test/orders",
            business_token_header="X-Token",
        )
        tool_view = MCPToolView(**request.model_dump(), input_schema=request.build_input_schema())

        with self.assertRaises(HTTPToolExecutionError) as error_context:
            await HTTPAPIToolExecutor().execute(tool_view, {}, runtime_credentials={})
        self.assertEqual(error_context.exception.code, "BUSINESS_CREDENTIAL_MISSING")

    async def test_business_token_rejects_control_characters(self) -> None:
        """业务凭证包含换行等控制字符时必须拒绝，避免目标 Header 注入。"""
        request = MCPToolUpsertRequest(
            name="query_order",
            platform_ids=[1],
            api_url="http://business.test/orders",
            business_token_header="X-Token",
        )
        tool_view = MCPToolView(**request.model_dump(), input_schema=request.build_input_schema())

        with self.assertRaises(HTTPToolExecutionError) as error_context:
            await HTTPAPIToolExecutor().execute(
                tool_view,
                {},
                runtime_credentials={"business_token": "unsafe\r\nX-Forged: true"},
            )
        self.assertEqual(error_context.exception.code, "BUSINESS_CREDENTIAL_INVALID_FORMAT")

    async def test_business_token_header_conflicts_are_rejected(self) -> None:
        """业务 Token 请求头不能与固定请求头或普通 Header 参数映射重名。"""
        with self.assertRaises(ValidationError):
            MCPToolUpsertRequest(
                name="static_conflict",
                platform_ids=[1],
                api_url="http://business.test/orders",
                static_headers={"x-token": "fixed"},
                business_token_header="X-Token",
            )

        with self.assertRaises(ValidationError):
            MCPToolUpsertRequest(
                name="parameter_conflict",
                platform_ids=[1],
                api_url="http://business.test/orders",
                business_token_header="X-Token",
                parameters=[
                    {"name": "x-token", "location": "header", "source": "tool"},
                ],
            )

    async def test_business_api_permission_statuses_use_stable_error_codes(self) -> None:
        """目标业务 API 的 401 和 403 应转换为稳定且不包含响应正文的权限错误。"""
        request = MCPToolUpsertRequest(
            name="query_order",
            platform_ids=[1],
            api_url="http://business.test/orders",
            business_token_header="X-Token",
        )
        tool_view = MCPToolView(**request.model_dump(), input_schema=request.build_input_schema())

        for status_code, expected_code in (
            (401, "BUSINESS_CREDENTIAL_INVALID"),
            (403, "BUSINESS_PERMISSION_DENIED"),
        ):
            async def return_permission_error(_client, **request_kwargs):
                """返回包含敏感模拟正文的目标业务权限错误。"""
                return httpx.Response(
                    status_code=status_code,
                    json={"detail": "sensitive-business-detail"},
                    request=httpx.Request(request_kwargs["method"], request_kwargs["url"]),
                )

            with self.subTest(status_code=status_code):
                with patch.object(httpx.AsyncClient, "request", new=return_permission_error):
                    with self.assertRaises(HTTPToolExecutionError) as error_context:
                        await HTTPAPIToolExecutor().execute(
                            tool_view,
                            {},
                            runtime_credentials={"business_token": "current-user-token"},
                        )
                self.assertEqual(error_context.exception.code, expected_code)
                self.assertEqual(error_context.exception.status_code, status_code)
                self.assertNotIn("sensitive-business-detail", str(error_context.exception))


class FastMCPToolRegistryTestCase(unittest.IsolatedAsyncioTestCase):
    """验证数据库配置可以动态注册和热移除 FastMCP Tool。"""

    async def test_registry_adds_and_removes_dynamic_tool(self) -> None:
        """enabled 配置应发布 Tool，disabled 配置应立即移除同名 Tool。"""
        server = FastMCP("registry-test", on_duplicate="replace")
        executor = AsyncMock()
        executor.execute.return_value = HTTPToolExecutionResult(
            status_code=200,
            elapsed_ms=1,
            data={"ok": True},
        )
        registry = FastMCPToolRegistry(server, executor=executor)
        enabled_view = MCPToolView(
            name="search_jobs",
            description="搜索职位",
            api_url="http://business.test/jobs",
            http_method="GET",
            timeout_seconds=30,
            status="enabled",
            input_schema={
                "type": "object",
                "properties": {"keyword": {"type": "string"}},
                "required": ["keyword"],
                "additionalProperties": False,
            },
        )

        registry.apply_tool_view(enabled_view)
        published_tools = await server.list_tools(run_middleware=False)
        self.assertEqual([tool.name for tool in published_tools], ["search_jobs"])
        self.assertEqual(published_tools[0].parameters, enabled_view.input_schema)

        # 使用 FastMCP Client 真正走一遍 MCP tools/list 与 tools/call，而非直接调用闭包。
        async with Client(server) as client:
            protocol_tools = await client.list_tools()
            call_result = await client.call_tool("search_jobs", {"keyword": "Python"})
        self.assertEqual([tool.name for tool in protocol_tools], ["search_jobs"])
        self.assertEqual(call_result.structured_content, {"ok": True})
        executor.execute.assert_awaited_once()

        disabled_view = enabled_view.model_copy(update={"status": "disabled"})
        registry.apply_tool_view(disabled_view)
        published_tools = await server.list_tools(run_middleware=False)
        self.assertEqual(list(published_tools), [])


if __name__ == "__main__":
    unittest.main()
