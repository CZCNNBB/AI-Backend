import unittest
from unittest.mock import AsyncMock, patch

import httpx
from fastmcp import Client, FastMCP
from pydantic import ValidationError

from app.server.fastmcp.src.executor import HTTPAPIToolExecutor, HTTPToolExecutionResult
from app.server.fastmcp.src.registry import FastMCPToolRegistry
from app.server.fastmcp.src.schemas import MCPToolUpsertRequest, MCPToolView


class HTTPAPIToolExecutorTestCase(unittest.IsolatedAsyncioTestCase):
    """验证参数映射、请求头和认证不会依赖单工具 Python 代码。"""

    async def test_execute_maps_all_parameter_sources_and_locations(self) -> None:
        """tool/runtime/static 参数应正确进入 path、query、header 和 JSON body。"""
        request = MCPToolUpsertRequest(
            name="get_job",
            platform_ids=[1],
            api_url="http://business.test/jobs/{job_id}",
            http_method="POST",
            static_headers={"X-App-Id": "ai-platform"},
            auth_type="bearer",
            auth_config={"token": "secret-token"},
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

    async def test_runtime_bearer_uses_only_runtime_credentials(self) -> None:
        """runtime_bearer 应使用独立运行时凭证，并覆盖固定 Authorization 请求头。"""
        request = MCPToolUpsertRequest(
            name="query_order",
            platform_ids=[1],
            api_url="http://business.test/orders",
            static_headers={"Authorization": "Bearer unsafe-static-token"},
            auth_type="runtime_bearer",
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
                runtime_credentials={"authorization": "Bearer current-user-token"},
            )

        self.assertEqual(
            captured_request["headers"]["Authorization"],
            "Bearer current-user-token",
        )

    async def test_runtime_bearer_rejects_missing_runtime_credentials(self) -> None:
        """runtime_bearer 缺少本次用户 Token 时必须在发出 HTTP 请求前失败。"""
        request = MCPToolUpsertRequest(
            name="query_order",
            platform_ids=[1],
            api_url="http://business.test/orders",
            auth_type="runtime_bearer",
        )
        tool_view = MCPToolView(**request.model_dump(), input_schema=request.build_input_schema())

        with self.assertRaisesRegex(RuntimeError, "未提供业务平台用户凭证"):
            await HTTPAPIToolExecutor().execute(tool_view, {}, runtime_credentials={})


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
            auth_type="none",
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
