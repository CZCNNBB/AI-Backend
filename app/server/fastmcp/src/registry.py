"""数据库驱动的 FastMCP 动态 Tool 注册中心。"""

from threading import RLock
from typing import Any

from fastmcp import FastMCP
from fastmcp.tools.function_tool import FunctionTool

from app.common.db.postgres_db import postgres_transaction
from app.server.fastmcp.src.executor import HTTPAPIToolExecutor
from app.server.fastmcp.src.repository import MCPToolRepository
from app.server.fastmcp.src.schemas import MCPToolParameter, MCPToolView


class FastMCPToolRegistry:
    """把已发布数据库记录热注册到一个共享 FastMCP Server。"""

    def __init__(
        self,
        server: FastMCP,
        repository: MCPToolRepository | None = None,
        executor: HTTPAPIToolExecutor | None = None,
    ) -> None:
        """初始化动态注册中心，但不在导入阶段访问数据库。"""
        self.server = server
        self.repository = repository or MCPToolRepository()
        self.executor = executor or HTTPAPIToolExecutor()
        self._registered_names: set[str] = set()
        self._lock = RLock()

    def reload_from_database(self) -> int:
        """在启动阶段从数据库重建全部已发布 Tool。"""
        with postgres_transaction() as db:
            records = self.repository.list_enabled_tools(db)
            tool_views = [self._record_to_view(record) for record in records]

        with self._lock:
            for registered_name in list(self._registered_names):
                self._remove_without_lock(registered_name)
            for tool_view in tool_views:
                self._register_without_lock(tool_view)
        return len(tool_views)

    def apply_tool_view(self, tool_view: MCPToolView) -> None:
        """根据最新状态新增、替换或移除单个动态 Tool。"""
        with self._lock:
            self._remove_without_lock(tool_view.name)
            if tool_view.status == "enabled":
                self._register_without_lock(tool_view)

    def remove(self, tool_name: str) -> None:
        """从当前进程的 FastMCP Server 移除一个 Tool。"""
        with self._lock:
            self._remove_without_lock(tool_name)

    def registered_names(self) -> set[str]:
        """返回当前进程已经发布的 Tool 名称快照。"""
        with self._lock:
            return set(self._registered_names)

    def _register_without_lock(self, tool_view: MCPToolView) -> None:
        """创建通用执行闭包并注册 Tool；调用方必须已经持有锁。"""
        async def invoke_http_api(**arguments: Any) -> Any:
            """使用当前工具配置调用目标 HTTP API。"""
            execution_result = await self.executor.execute(tool_view, arguments)
            return execution_result.data

        output_schema = tool_view.output_schema
        if output_schema and output_schema.get("type") != "object":
            # MCP 规范只接受 object 类型的结构化输出 Schema；其他响应仍可作为文本/JSON 返回。
            output_schema = None

        dynamic_tool = FunctionTool(
            name=tool_view.name,
            description=tool_view.description,
            parameters=tool_view.input_schema,
            output_schema=output_schema,
            fn=invoke_http_api,
            return_type=Any,
            timeout=tool_view.timeout_seconds,
            run_in_thread=False,
        )
        self.server.local_provider.add_tool(dynamic_tool)
        self._registered_names.add(tool_view.name)

    def _remove_without_lock(self, tool_name: str) -> None:
        """移除已知 Tool；调用方必须已经持有锁。"""
        if tool_name not in self._registered_names:
            return
        try:
            self.server.local_provider.remove_tool(tool_name)
        except KeyError:
            # 注册集合与 Provider 偶尔可能因测试替换而不同步，移除操作保持幂等。
            pass
        self._registered_names.discard(tool_name)

    @staticmethod
    def _record_to_view(record: Any) -> MCPToolView:
        """把 ORM 记录复制成脱离 Session 的不可变运行配置。"""
        return MCPToolView(
            id=record.id,
            name=record.name,
            description=record.description,
            api_url=record.api_url,
            http_method=record.http_method,
            static_headers=dict(record.static_headers or {}),
            parameters=[MCPToolParameter.model_validate(item) for item in (record.parameters or [])],
            business_token_header=record.business_token_header,
            input_schema=dict(record.input_schema or {}),
            output_schema=dict(record.output_schema) if record.output_schema else None,
            timeout_seconds=record.timeout_seconds,
            status=record.status,
            created_at=record.created_at.isoformat() if record.created_at else None,
            updated_at=record.updated_at.isoformat() if record.updated_at else None,
        )
