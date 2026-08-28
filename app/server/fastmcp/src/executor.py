"""把 MCP Tool 参数组装为普通 HTTP 请求的统一执行器。"""

import base64
import json
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx
from fastmcp.server.dependencies import get_http_headers

from app.server.fastmcp.src.schemas import MCPToolParameter, MCPToolView


RUNTIME_INPUTS_HEADER = "x-agent-runtime-inputs"
RUNTIME_CREDENTIALS_HEADER = "x-agent-runtime-credentials"


@dataclass(frozen=True)
class HTTPToolExecutionResult:
    """保存一次目标 HTTP API 调用的结构化结果。"""

    status_code: int
    elapsed_ms: int
    data: Any


class HTTPToolExecutionError(RuntimeError):
    """表示一次可以安全暴露给 Agent 的目标业务 API 调用错误。"""

    def __init__(self, code: str, message: str, *, status_code: int | None = None) -> None:
        """保存稳定错误码、可读消息和可选 HTTP 状态码。"""
        self.code = code
        self.status_code = status_code
        self.message = message
        super().__init__(f"{code}: {message}")


class HTTPAPIToolExecutor:
    """根据数据库配置执行任意普通 JSON HTTP API。"""

    async def execute(
        self,
        tool: MCPToolView,
        arguments: dict[str, Any],
        runtime_inputs: dict[str, Any] | None = None,
        runtime_credentials: dict[str, str] | None = None,
    ) -> HTTPToolExecutionResult:
        """组装并调用目标 API，返回状态码、耗时和响应数据。"""
        resolved_runtime_inputs = runtime_inputs
        if resolved_runtime_inputs is None:
            # Agent 调用 MCP Endpoint 时，完整 inputs 由 Adapter 拦截器放入可信请求头。
            resolved_runtime_inputs = self._read_runtime_inputs_from_mcp_request()
        resolved_runtime_credentials = runtime_credentials
        if resolved_runtime_credentials is None:
            resolved_runtime_credentials = self._read_runtime_credentials_from_mcp_request()

        request_url = tool.api_url
        request_headers = self._normalize_headers(tool.static_headers)
        query_params: dict[str, Any] = {}
        json_body: dict[str, Any] = {}

        for parameter in tool.parameters:
            has_value, parameter_value = self._resolve_parameter_value(
                parameter,
                arguments,
                resolved_runtime_inputs,
            )
            if not has_value:
                continue

            if parameter.location == "path":
                request_url = self._replace_path_parameter(request_url, parameter.name, parameter_value)
            elif parameter.location == "query":
                query_params[parameter.name] = parameter_value
            elif parameter.location == "header":
                request_headers[parameter.name] = self._stringify_header_value(parameter_value)
            elif parameter.location == "body":
                self._set_nested_value(json_body, parameter.name, parameter_value)

        self._apply_business_token(
            tool,
            request_headers,
            resolved_runtime_credentials,
        )

        request_kwargs: dict[str, Any] = {
            "method": tool.http_method,
            "url": request_url,
            "headers": request_headers,
            "params": query_params,
        }
        if json_body:
            request_kwargs["json"] = json_body

        started_at = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=tool.timeout_seconds, follow_redirects=True) as client:
                response = await client.request(**request_kwargs)
        except httpx.RequestError as error:
            raise RuntimeError(f"目标 API 请求失败: {error}") from error

        elapsed_ms = int((time.perf_counter() - started_at) * 1000)
        response_data = self._parse_response_data(response)
        if response.status_code == 401:
            # 认证失败时不拼接业务响应正文，避免上游把敏感认证细节带入 Agent 上下文。
            raise HTTPToolExecutionError(
                "BUSINESS_CREDENTIAL_INVALID",
                "业务用户凭证无效或已过期",
                status_code=401,
            )
        if response.status_code == 403:
            raise HTTPToolExecutionError(
                "BUSINESS_PERMISSION_DENIED",
                "当前业务用户没有执行该操作的权限",
                status_code=403,
            )
        if not response.is_success:
            # 错误正文限制长度，避免上游返回超大 HTML 时污染 MCP 错误消息。
            error_preview = str(response_data)[:1000]
            raise RuntimeError(f"目标 API 返回 HTTP {response.status_code}: {error_preview}")

        return HTTPToolExecutionResult(
            status_code=response.status_code,
            elapsed_ms=elapsed_ms,
            data=response_data,
        )

    def _resolve_parameter_value(
        self,
        parameter: MCPToolParameter,
        arguments: dict[str, Any],
        runtime_inputs: dict[str, Any],
    ) -> tuple[bool, Any]:
        """按 tool、runtime、static 三种来源解析一个映射参数。"""
        if parameter.source == "tool":
            if parameter.name in arguments:
                return True, arguments[parameter.name]
            if parameter.default is not None:
                return True, parameter.default
        elif parameter.source == "runtime":
            runtime_path = parameter.runtime_path or parameter.name
            found, value = self._read_nested_value(runtime_inputs, runtime_path)
            if found:
                return True, value
        else:
            # static 参数允许显式配置 null，因此不通过 value is None 判断是否存在。
            return True, parameter.value

        if parameter.required:
            raise RuntimeError(f"缺少必填参数: {parameter.name}")
        return False, None

    def _apply_business_token(
        self,
        tool: MCPToolView,
        headers: dict[str, str],
        runtime_credentials: dict[str, str],
    ) -> None:
        """按 Tool 配置把本次业务用户凭证原样写入目标 API 请求头。"""
        target_header_name = tool.business_token_header
        if not target_header_name:
            return

        credential_value = runtime_credentials.get("business_token")
        if credential_value in (None, ""):
            raise HTTPToolExecutionError(
                "BUSINESS_CREDENTIAL_MISSING",
                "当前操作需要业务用户凭证，请重新登录或重新发起请求",
            )

        # 凭证内容保持原样，平台不添加 Bearer 等前缀；仅拒绝可能造成 Header 注入的控制字符。
        if any(ord(character) < 32 or ord(character) == 127 for character in credential_value):
            raise HTTPToolExecutionError(
                "BUSINESS_CREDENTIAL_INVALID_FORMAT",
                "业务用户凭证包含非法控制字符",
            )
        headers[target_header_name] = credential_value

    @staticmethod
    def _read_runtime_inputs_from_mcp_request() -> dict[str, Any]:
        """从当前 FastMCP HTTP 请求头解码 Agent Runtime inputs。"""
        try:
            request_headers = get_http_headers(include_all=True)
        except RuntimeError:
            # 管理接口直接测试执行器时不存在 FastMCP 请求上下文，按空 inputs 处理。
            return {}

        encoded_inputs = request_headers.get(RUNTIME_INPUTS_HEADER)
        if not encoded_inputs:
            return {}
        try:
            decoded_payload = base64.urlsafe_b64decode(encoded_inputs.encode("ascii"))
            parsed_payload = json.loads(decoded_payload.decode("utf-8"))
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
            raise RuntimeError("Agent Runtime inputs 请求头格式无效") from None
        return dict(parsed_payload) if isinstance(parsed_payload, dict) else {}

    @staticmethod
    def _read_runtime_credentials_from_mcp_request() -> dict[str, str]:
        """从当前 FastMCP HTTP 请求头解码独立的运行时凭证。"""
        try:
            request_headers = get_http_headers(include_all=True)
        except RuntimeError:
            # 管理接口直接执行时不存在 MCP 请求上下文，由调用方显式提供测试凭证。
            return {}

        encoded_credentials = request_headers.get(RUNTIME_CREDENTIALS_HEADER)
        if not encoded_credentials:
            return {}
        try:
            decoded_payload = base64.urlsafe_b64decode(encoded_credentials.encode("ascii"))
            parsed_payload = json.loads(decoded_payload.decode("utf-8"))
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
            raise RuntimeError("Agent Runtime credentials 请求头格式无效") from None
        if not isinstance(parsed_payload, dict):
            return {}
        return {
            str(key): str(value)
            for key, value in parsed_payload.items()
            if value not in (None, "")
        }

    @staticmethod
    def _read_nested_value(data: dict[str, Any], dotted_path: str) -> tuple[bool, Any]:
        """使用点分路径从 runtime inputs 中读取嵌套值。"""
        current_value: Any = data
        for path_part in dotted_path.split("."):
            if not isinstance(current_value, dict) or path_part not in current_value:
                return False, None
            current_value = current_value[path_part]
        return True, current_value

    @staticmethod
    def _set_nested_value(target: dict[str, Any], dotted_path: str, value: Any) -> None:
        """使用点分目标名构造嵌套 JSON body。"""
        path_parts = dotted_path.split(".")
        current_target = target
        for path_part in path_parts[:-1]:
            nested_target = current_target.get(path_part)
            if not isinstance(nested_target, dict):
                nested_target = {}
                current_target[path_part] = nested_target
            current_target = nested_target
        current_target[path_parts[-1]] = value

    @staticmethod
    def _replace_path_parameter(url: str, target_name: str, value: Any) -> str:
        """替换 URL 中的 ``{参数名}``，并对动态值执行 URL 编码。"""
        placeholder = "{" + target_name + "}"
        if placeholder not in url:
            raise RuntimeError(f"API URL 中不存在 path 占位符: {placeholder}")
        encoded_value = quote(str(value), safe="")
        return url.replace(placeholder, encoded_value)

    @staticmethod
    def _normalize_headers(headers: dict[str, Any]) -> dict[str, str]:
        """把数据库中的固定请求头统一转换为 HTTP 字符串值。"""
        return {str(key): HTTPAPIToolExecutor._stringify_header_value(value) for key, value in headers.items()}

    @staticmethod
    def _stringify_header_value(value: Any) -> str:
        """把简单值或结构化值转换为合法请求头文本。"""
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        return str(value)

    @staticmethod
    def _parse_response_data(response: httpx.Response) -> Any:
        """优先解析 JSON 响应，空响应返回状态对象，其余返回文本。"""
        if not response.content:
            return {"status_code": response.status_code}
        try:
            return response.json()
        except json.JSONDecodeError:
            return response.text
