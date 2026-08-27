"""MCP Runtime Context 完整 inputs 自动注入测试。"""

import unittest
from types import SimpleNamespace
from uuid import uuid4

from langchain_mcp_adapters.interceptors import MCPToolCallRequest

from app.server.agent.src.mcp.client import (
    MCPConnectionConfig,
    create_multi_server_client,
)
from app.server.agent.src.mcp.runtime_context_interceptor import (
    MCPRuntimeContextInterceptor,
    RUNTIME_CREDENTIALS_HEADER,
    RUNTIME_INPUTS_HEADER,
    RUN_ID_HEADER,
    encode_runtime_credentials,
    encode_runtime_inputs,
)


class MCPRuntimeContextInterceptorTestCase(unittest.IsolatedAsyncioTestCase):
    """验证所有 Agent MCP 调用都能透传完整 inputs。"""

    @staticmethod
    def _build_runtime() -> tuple[SimpleNamespace, dict[str, object]]:
        """构造包含嵌套业务数据的 LangGraph Runtime。"""
        values: dict[str, object] = {
            "user_id": str(uuid4()),
            "project_id": str(uuid4()),
            "branch_id": str(uuid4()),
            "node_id": str(uuid4()),
            "stage_code": "project_preparation",
            "project_context": {"name": "新品发布会", "tags": ["科技", "深圳"]},
        }
        context = SimpleNamespace(
            inputs=values,
            run_id="run-test",
            runtime_credentials={"authorization": "Bearer secret-user-token"},
        )
        return SimpleNamespace(context=context), values

    async def test_injects_complete_inputs_for_any_agent_mcp_tool(self) -> None:
        """任意 Agent MCP 工具调用都应携带完整编码 inputs，而非固定字段映射。"""
        runtime, values = self._build_runtime()
        interceptor = MCPRuntimeContextInterceptor()
        captured_request = None

        async def handler(request):
            """捕获拦截器传给远程 MCP 执行器的请求。"""
            nonlocal captured_request
            captured_request = request
            return "ok"

        result = await interceptor(
            MCPToolCallRequest(
                name="save_stage_result",
                args={"result": {"goal": "新品发布"}},
                server_name="hai-agent",
                runtime=runtime,
            ),
            handler,
        )

        self.assertEqual(result, "ok")
        self.assertIsNotNone(captured_request)
        self.assertEqual(
            captured_request.headers[RUNTIME_INPUTS_HEADER],
            encode_runtime_inputs(values),
        )
        self.assertEqual(captured_request.headers[RUN_ID_HEADER], "run-test")
        self.assertEqual(
            captured_request.headers[RUNTIME_CREDENTIALS_HEADER],
            encode_runtime_credentials({"authorization": "Bearer secret-user-token"}),
        )

    async def test_regular_mcp_tool_also_receives_complete_inputs(self) -> None:
        """普通 MCP 工具在 Agent 中运行时也应获得相同的完整 inputs。"""
        runtime, values = self._build_runtime()
        interceptor = MCPRuntimeContextInterceptor()

        async def handler(request):
            """直接返回处理器收到的 MCP 请求。"""
            return request

        handled_request = await interceptor(
            MCPToolCallRequest(
                name="search_job_skills",
                args={"keywords": ["Python"]},
                server_name="orchestration",
                runtime=runtime,
            ),
            handler,
        )

        self.assertEqual(
            handled_request.headers[RUNTIME_INPUTS_HEADER],
            encode_runtime_inputs(values),
        )

    async def test_mcp_tool_without_agent_runtime_remains_unchanged(self) -> None:
        """工具管理页等脱离 Agent 的 MCP 测试不应强制要求 Runtime Context。"""
        interceptor = MCPRuntimeContextInterceptor()
        original_request = MCPToolCallRequest(
            name="search_job_skills",
            args={"keywords": ["Python"]},
            server_name="orchestration",
            runtime=None,
        )

        async def handler(request):
            """直接返回处理器收到的 MCP 请求。"""
            return request

        handled_request = await interceptor(original_request, handler)
        self.assertIs(handled_request, original_request)
        self.assertIsNone(handled_request.headers)

    def test_multi_server_client_installs_runtime_interceptor(self) -> None:
        """所有动态加载的 MCP 工具客户端都应安装完整 inputs 拦截器。"""
        client = create_multi_server_client([
            MCPConnectionConfig(
                key="hai_agent",
                base_url="http://127.0.0.1:8093/mcp/",
            )
        ])
        self.assertTrue(
            any(isinstance(item, MCPRuntimeContextInterceptor) for item in client.tool_interceptors)
        )


if __name__ == "__main__":
    unittest.main()
