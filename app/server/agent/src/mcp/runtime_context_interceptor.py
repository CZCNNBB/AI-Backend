"""把 Agent 的完整 inputs 注入所有 MCP 工具请求。"""

import base64
import json
from collections.abc import Awaitable, Callable
from typing import Any

from langchain_mcp_adapters.interceptors import (
    MCPToolCallRequest,
    MCPToolCallResult,
)


RUNTIME_INPUTS_HEADER = "X-Agent-Runtime-Inputs"
RUN_ID_HEADER = "X-Agent-Run-Id"


def encode_runtime_inputs(inputs: dict[str, Any]) -> str:
    """把完整 inputs 编码为可安全放入 HTTP 请求头的文本。"""
    payload = json.dumps(
        inputs,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii")


class MCPRuntimeContextInterceptor:
    """为 Agent 发起的 MCP 调用统一透传完整 Runtime Context inputs。"""

    async def __call__(
        self,
        request: MCPToolCallRequest,
        handler: Callable[[MCPToolCallRequest], Awaitable[MCPToolCallResult]],
    ) -> MCPToolCallResult:
        """存在 Agent Runtime Context 时编码完整 inputs，然后继续执行 MCP 工具。"""
        context = self._get_runtime_context(request)
        if context is None:
            return await handler(request)

        inputs = self._get_context_inputs(context)
        headers = dict(request.headers or {})
        headers[RUNTIME_INPUTS_HEADER] = encode_runtime_inputs(inputs)

        run_id = self._get_context_value(context, "run_id")
        if run_id not in (None, ""):
            headers[RUN_ID_HEADER] = str(run_id)

        return await handler(request.override(headers=headers))

    @staticmethod
    def _get_runtime_context(request: MCPToolCallRequest) -> Any | None:
        """从适配器工具请求取得 LangGraph Runtime Context；工具测试可不携带。"""
        runtime = request.runtime

        if runtime is None:
            return None

        return getattr(runtime, "context", None)

    @staticmethod
    def _get_context_inputs(context: Any) -> dict[str, Any]:
        """兼容字典和 Pydantic Context，提取完整 inputs。"""
        if isinstance(context, dict):
            inputs = context.get("inputs")
        elif hasattr(context, "model_dump"):
            inputs = context.model_dump().get("inputs")
        else:
            inputs = getattr(context, "inputs", None)
        return dict(inputs) if isinstance(inputs, dict) else {}

    @staticmethod
    def _get_context_value(context: Any, key: str) -> Any:
        """从字典或对象形式 Context 读取普通运行字段。"""
        if isinstance(context, dict):
            return context.get(key)
        if hasattr(context, "model_dump"):
            return context.model_dump().get(key)
        return getattr(context, key, None)
