from typing import Any

from sqlmodel import Session

from app.common.core.exceptions import BusinessException
from app.common.db.postgres_db import postgres_transaction
from app.server.fastmcp.src.executor import HTTPAPIToolExecutor
from app.server.fastmcp.src.models import MCPToolRecord
from app.server.fastmcp.src.registry import FastMCPToolRegistry
from app.server.fastmcp.src.repository import MCPToolRepository
from app.server.fastmcp.src.schemas import (
    MCPToolDeleteRequest,
    MCPToolDetailRequest,
    MCPToolInvokeRequest,
    MCPToolParameter,
    MCPToolPublishRequest,
    MCPToolSearchRequest,
    MCPToolSearchResponse,
    MCPToolTestRequest,
    MCPToolTestResponse,
    MCPToolUpsertRequest,
    MCPToolView,
)
from app.server.fastmcp.src.server import fastmcp_registry


class MCPToolService:
    """管理 HTTP API 配置，并协调 FastMCP Tool 的测试与热发布。"""

    def __init__(
        self,
        repository: MCPToolRepository | None = None,
        registry: FastMCPToolRegistry | None = None,
        executor: HTTPAPIToolExecutor | None = None,
    ) -> None:
        """初始化 MCP Tool 服务及其可替换依赖。"""
        self.repository = repository or MCPToolRepository()
        self.registry = registry or fastmcp_registry
        self.executor = executor or HTTPAPIToolExecutor()

    def upsert_tool(self, db: Session, request: MCPToolUpsertRequest) -> MCPToolView:
        """保存 API 配置，并按 status 在当前进程热注册或移除 Tool。"""
        record = self.repository.upsert_tool(
            db,
            name=request.name,
            description=request.description,
            api_url=request.api_url,
            http_method=request.http_method,
            static_headers=request.static_headers,
            parameters=[parameter.model_dump(mode="json") for parameter in request.parameters],
            auth_type=request.auth_type,
            auth_config=request.auth_config,
            input_schema=request.build_input_schema(),
            output_schema=request.output_schema,
            timeout_seconds=request.timeout_seconds,
            status=request.status,
        )
        tool_view = self.to_tool_view(record)
        self.registry.apply_tool_view(tool_view)
        return tool_view

    def get_tool(self, db: Session, request: MCPToolDetailRequest) -> MCPToolView | None:
        """根据名称查询一个 HTTP API 转换型 MCP Tool。"""
        record = self.repository.get_tool_by_name(db, request.name)
        return self.to_tool_view(record) if record else None

    def search_tools(self, db: Session, request: MCPToolSearchRequest) -> MCPToolSearchResponse:
        """分页查询 MCP Tool 配置。"""
        rows, total = self.repository.list_tools(
            db,
            keyword=request.keyword,
            status=request.status,
            api_url=request.api_url,
            page=request.page,
            page_size=request.page_size,
        )
        return MCPToolSearchResponse(
            total=total,
            page=request.page,
            page_size=request.page_size,
            items=[self.to_tool_view(row) for row in rows],
        )

    def delete_tools(self, db: Session, request: MCPToolDeleteRequest) -> int:
        """删除数据库配置，并立即从当前 FastMCP 进程移除对应 Tool。"""
        deleted_count = self.repository.delete_tools_by_names(db, request.names)
        for tool_name in request.names:
            self.registry.remove(tool_name)
        return deleted_count

    def publish_tool(self, db: Session, request: MCPToolPublishRequest) -> MCPToolView:
        """发布或停用一个工具，并同步更新当前进程的 Registry。"""
        record = self.repository.get_tool_by_name(db, request.name)
        if record is None:
            raise BusinessException(code=404, msg=f"MCP Tool 不存在: {request.name}")
        new_status = "enabled" if request.enabled else "disabled"
        updated_record = self.repository.update_status(db, record, new_status)
        tool_view = self.to_tool_view(updated_record)
        self.registry.apply_tool_view(tool_view)
        return tool_view

    async def test_tool(self, db: Session, request: MCPToolTestRequest) -> MCPToolTestResponse:
        """不经过 Agent，直接验证参数映射、认证配置和目标 API 连通性。"""
        if request.tool is not None:
            tool_view = self._request_to_tool_view(request.tool)
        else:
            record = self.repository.get_tool_by_name(db, request.name or "")
            if record is None:
                raise BusinessException(code=404, msg=f"MCP Tool 不存在: {request.name}")
            tool_view = self.to_tool_view(record)

        execution_result = await self.executor.execute(
            tool_view,
            request.args,
            runtime_inputs=request.runtime_inputs,
        )
        return MCPToolTestResponse(
            ok=True,
            status_code=execution_result.status_code,
            elapsed_ms=execution_result.elapsed_ms,
            data=execution_result.data,
        )

    async def invoke_tool(self, db: Session, request: MCPToolInvokeRequest) -> Any:
        """通过管理接口直接调用一个已发布工具，便于联调。"""
        record = self.repository.get_tool_by_name(db, request.name)
        if record is None or record.status != "enabled":
            raise BusinessException(code=404, msg=f"MCP Tool 不存在或未发布: {request.name}")
        execution_result = await self.executor.execute(
            self.to_tool_view(record),
            request.args,
            runtime_inputs=request.runtime_inputs,
        )
        return execution_result.data

    def get_enabled_tool_views(self, db: Session, tool_names: list[str]) -> list[MCPToolView]:
        """在短事务内查询并复制 Agent 指定的已发布 Tool 配置。"""
        records = self._get_enabled_tool_records(db, tool_names)
        return [self.to_tool_view(record) for record in records]

    def load_enabled_tool_snapshots(self, tool_names: list[str]) -> list[MCPToolView]:
        """使用独立短事务加载配置，远程 MCP 发现阶段不持有数据库连接。"""
        with postgres_transaction() as config_db:
            return self.get_enabled_tool_views(config_db, tool_names)

    def _get_enabled_tool_records(self, db: Session, tool_names: list[str]) -> list[MCPToolRecord]:
        """查询并校验 Agent 声明的 Tool 全部存在且处于发布状态。"""
        if not tool_names:
            return []
        records = self.repository.list_enabled_tools_by_names(db, tool_names)
        record_by_name = {record.name: record for record in records}
        missing_names = [name for name in tool_names if name not in record_by_name]
        if missing_names:
            raise RuntimeError(f"MCP Tool 不存在或未发布: {', '.join(missing_names)}")
        return [record_by_name[name] for name in tool_names]

    @staticmethod
    def _request_to_tool_view(request: MCPToolUpsertRequest) -> MCPToolView:
        """把未保存的前端配置转换为可供统一执行器测试的视图。"""
        return MCPToolView(
            name=request.name,
            description=request.description,
            api_url=request.api_url,
            http_method=request.http_method,
            static_headers=request.static_headers,
            parameters=request.parameters,
            auth_type=request.auth_type,
            auth_config=request.auth_config,
            input_schema=request.build_input_schema(),
            output_schema=request.output_schema,
            timeout_seconds=request.timeout_seconds,
            status=request.status,
        )

    @staticmethod
    def to_tool_view(record: MCPToolRecord) -> MCPToolView:
        """把 ORM 记录复制为脱离 Session 的管理与运行时视图。"""
        return MCPToolView(
            id=record.id,
            name=record.name,
            description=record.description,
            api_url=record.api_url,
            http_method=record.http_method,
            static_headers=dict(record.static_headers or {}),
            parameters=[MCPToolParameter.model_validate(item) for item in (record.parameters or [])],
            auth_type=record.auth_type,
            auth_config=dict(record.auth_config or {}),
            input_schema=dict(record.input_schema or {}),
            output_schema=dict(record.output_schema) if record.output_schema else None,
            timeout_seconds=record.timeout_seconds,
            status=record.status,
            created_at=record.created_at.isoformat() if record.created_at else None,
            updated_at=record.updated_at.isoformat() if record.updated_at else None,
        )
