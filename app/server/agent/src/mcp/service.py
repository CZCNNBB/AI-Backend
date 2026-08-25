from collections import defaultdict
from typing import Any

from sqlmodel import Session

from app.common.core.exceptions import BusinessException
from app.server.agent.src.mcp.client import MCPConnectionConfig, create_multi_server_client
from app.server.agent.src.mcp.models import AgentMCPToolRecord
from app.server.agent.src.mcp.repository import MCPRepository
from app.server.agent.src.mcp.schemas import (
    AgentMCPToolDeleteRequest,
    AgentMCPToolDetailRequest,
    AgentMCPToolInvokeRequest,
    AgentMCPToolSearchRequest,
    AgentMCPToolSearchResponse,
    AgentMCPToolSyncRequest,
    AgentMCPToolSyncResponse,
    AgentMCPToolTestRequest,
    AgentMCPToolTestResponse,
    AgentMCPToolUpsertRequest,
    AgentMCPToolView,
)


class MCPService:
    """Agent MCP 服务层，负责 MCP 工具配置、同步、测试和运行时工具加载。"""

    def __init__(self, repository: MCPRepository | None = None):
        """初始化 MCP 服务层。

        Args:
            repository: MCP 数据访问对象；不传时使用默认仓储。
        """
        self.repository = repository or MCPRepository()

    def upsert_tool(self, db: Session, request: AgentMCPToolUpsertRequest) -> AgentMCPToolView:
        """新增或更新 MCP 工具配置。"""
        try:
            record = self.repository.upsert_tool(
                db,
                mcp_code=request.mcp_code,
                original_mcp_code=request.original_mcp_code,
                name=request.name,
                description=request.description,
                base_url=request.base_url,
                transport=request.transport,
                auth_type=request.auth_type,
                auth_config=request.auth_config,
                input_schema=request.input_schema,
                output_schema=request.output_schema,
                status=request.status,
            )
        except RuntimeError as error:
            raise BusinessException(code=400, msg=str(error)) from error
        return self.to_tool_view(record)

    def get_tool(self, db: Session, request: AgentMCPToolDetailRequest) -> AgentMCPToolView | None:
        """根据平台 MCP 工具编码查询工具详情。"""
        record = self.repository.get_tool_by_code(db, request.mcp_code)
        return self.to_tool_view(record) if record else None

    def search_tools(self, db: Session, request: AgentMCPToolSearchRequest) -> AgentMCPToolSearchResponse:
        """分页查询 MCP 工具配置列表。"""
        rows, total = self.repository.list_tools(
            db,
            keyword=request.keyword,
            status=request.status,
            base_url=request.base_url,
            page=request.page,
            page_size=request.page_size,
        )
        return AgentMCPToolSearchResponse(
            total=total,
            page=request.page,
            page_size=request.page_size,
            items=[self.to_tool_view(row) for row in rows],
        )

    def delete_tools(self, db: Session, request: AgentMCPToolDeleteRequest) -> int:
        """批量删除 MCP 工具配置。"""
        return self.repository.delete_tools_by_codes(db, request.mcp_codes)

    async def test_tools(self, db: Session, request: AgentMCPToolTestRequest) -> AgentMCPToolTestResponse:
        """测试 MCP 工具连接，并返回远程工具摘要。"""
        if request.mcp_code:
            record = self.repository.get_tool_by_code(db, request.mcp_code)
            if record is None:
                raise BusinessException(code=404, msg=f"MCP 工具不存在: {request.mcp_code}")
            connections = self._group_connections([record])
        else:
            connections = [
                MCPConnectionConfig(
                    key="mcp_test",
                    base_url=request.base_url or "",
                    transport=request.transport,
                    auth_config=request.auth_config,
                )
            ]

        tools = await self._fetch_mcp_tools(connections)
        tool_items = [self._tool_to_summary(tool) for tool in tools]
        return AgentMCPToolTestResponse(ok=True, tool_count=len(tool_items), tools=tool_items)

    async def sync_tools(self, db: Session, request: AgentMCPToolSyncRequest) -> AgentMCPToolSyncResponse:
        """从一个 MCP 服务地址同步工具列表到 agent_mcp_tools。"""
        connection = MCPConnectionConfig(
            key="mcp_sync",
            base_url=request.base_url,
            transport=request.transport,
            auth_config=request.auth_config,
        )
        mcp_tools = await self._fetch_mcp_tools([connection])
        synced_records: list[AgentMCPToolRecord] = []

        for tool in mcp_tools:
            tool_name = str(getattr(tool, "name", "") or "").strip()
            if not tool_name:
                continue
            mcp_code = self.build_mcp_code(request.code_prefix, tool_name)
            record = self.repository.upsert_tool(
                db,
                mcp_code=mcp_code,
                name=tool_name,
                description=str(getattr(tool, "description", "") or ""),
                base_url=request.base_url,
                transport=request.transport,
                auth_type=request.auth_type,
                auth_config=request.auth_config,
                input_schema=self.extract_tool_input_schema(tool),
                output_schema=self.extract_tool_output_schema(tool),
                status="enabled",
                overwrite=request.overwrite,
            )
            synced_records.append(record)

        return AgentMCPToolSyncResponse(
            base_url=request.base_url,
            synced=len(synced_records),
            items=[self.to_tool_view(record) for record in synced_records],
        )

    async def invoke_tool(self, db: Session, request: AgentMCPToolInvokeRequest) -> Any:
        """直接调用一个已保存的 MCP 工具，用于工具管理页测试。"""
        tools = await self.load_langchain_tools(db, [request.mcp_code])
        if not tools:
            raise BusinessException(code=404, msg=f"MCP 工具不存在或未启用: {request.mcp_code}")
        tool = tools[0]
        if hasattr(tool, "ainvoke"):
            return await tool.ainvoke(request.args)
        if hasattr(tool, "invoke"):
            return tool.invoke(request.args)
        raise BusinessException(code=400, msg=f"MCP 工具不可调用: {request.mcp_code}")

    async def load_langchain_tools(self, db: Session, mcp_codes: list[str]) -> list[Any]:
        """根据平台 MCP 工具编码加载 LangChain 可用工具。"""
        if not mcp_codes:
            return []

        records = self.repository.list_enabled_tools_by_codes(db, mcp_codes)
        record_by_code = {record.mcp_code: record for record in records}
        missing_codes = [code for code in mcp_codes if code not in record_by_code]
        if missing_codes:
            raise RuntimeError(f"MCP 工具不存在或未启用: {', '.join(missing_codes)}")

        connections = self._group_connections(records)
        requested_names_by_connection = self._build_requested_names_by_connection(records, connections)
        langchain_tools = await self._fetch_mcp_tools(connections)

        selected_tools: list[Any] = []
        for tool in langchain_tools:
            connection_key, tool_name = self._split_loaded_tool_name(
                str(getattr(tool, "name", "") or ""),
                requested_names_by_connection,
            )
            if connection_key and tool_name in requested_names_by_connection[connection_key]:
                selected_tools.append(tool)

        if len(selected_tools) != len(mcp_codes):
            loaded_names = [str(getattr(tool, "name", "")) for tool in selected_tools]
            raise RuntimeError(f"MCP 工具加载数量不一致: requested={mcp_codes}, loaded={loaded_names}")
        return selected_tools

    async def _fetch_mcp_tools(self, connections: list[MCPConnectionConfig]) -> list[Any]:
        """通过 langchain-mcp-adapters 从 MCP 服务读取 LangChain 工具。"""
        client = create_multi_server_client(connections)
        return await client.get_tools()

    def _group_connections(self, records: list[AgentMCPToolRecord]) -> list[MCPConnectionConfig]:
        """按 base_url、transport 和认证配置对 MCP 工具记录做运行时连接分组。"""
        grouped: dict[tuple[str, str, str], MCPConnectionConfig] = {}
        for record in records:
            # auth_config 是 dict，不能直接作为 key；这里用稳定字符串参与分组即可。
            auth_key = repr(sorted((record.auth_config or {}).items()))
            group_key = (record.base_url, record.transport, auth_key)
            if group_key not in grouped:
                grouped[group_key] = MCPConnectionConfig(
                    key=f"mcp_{len(grouped) + 1}",
                    base_url=record.base_url,
                    transport=record.transport,
                    auth_config=record.auth_config,
                )
        return list(grouped.values())

    def _build_requested_names_by_connection(
        self,
        records: list[AgentMCPToolRecord],
        connections: list[MCPConnectionConfig],
    ) -> dict[str, set[str]]:
        """建立连接 key 到目标 MCP 工具名集合的映射。"""
        requested: dict[str, set[str]] = defaultdict(set)
        for record in records:
            connection = self._find_connection_for_record(record, connections)
            if connection is None:
                raise RuntimeError(f"MCP 工具缺少可用连接配置: {record.mcp_code}")
            requested[connection.key].add(record.name)
        return requested

    def _find_connection_for_record(
        self,
        record: AgentMCPToolRecord,
        connections: list[MCPConnectionConfig],
    ) -> MCPConnectionConfig | None:
        """查找某条 MCP 工具记录对应的运行时连接配置。"""
        for connection in connections:
            if (
                connection.base_url == record.base_url
                and connection.transport == record.transport
                and connection.auth_config == record.auth_config
            ):
                return connection
        return None

    def _split_loaded_tool_name(
        self,
        loaded_name: str,
        requested_names_by_connection: dict[str, set[str]],
    ) -> tuple[str | None, str]:
        """从适配器返回的工具名中推断连接 key 和 MCP 原始工具名。"""
        candidates: list[tuple[str, str]] = []
        for connection_key, names in requested_names_by_connection.items():
            if loaded_name in names:
                candidates.append((connection_key, loaded_name))
            for name in names:
                if loaded_name in {f"{connection_key}_{name}", f"{connection_key}__{name}", f"{connection_key}.{name}"}:
                    candidates.append((connection_key, name))
        if len(candidates) == 1:
            return candidates[0]
        if candidates:
            return candidates[0]
        return None, loaded_name

    def _tool_to_summary(self, tool: Any) -> dict[str, Any]:
        """把 LangChain Tool 转换为连接测试返回的摘要。"""
        return {
            "name": str(getattr(tool, "name", "") or ""),
            "description": str(getattr(tool, "description", "") or ""),
            "input_schema": self.extract_tool_input_schema(tool),
            "output_schema": self.extract_tool_output_schema(tool),
        }

    def extract_tool_input_schema(self, tool: Any) -> dict[str, Any] | None:
        """提取 MCP 工具的输入参数 Schema。"""
        args = getattr(tool, "args", None)
        if isinstance(args, dict):
            return args
        args_schema = getattr(tool, "args_schema", None)
        if args_schema is not None and hasattr(args_schema, "model_json_schema"):
            return args_schema.model_json_schema()
        return None

    def extract_tool_output_schema(self, tool: Any) -> dict[str, Any] | None:
        """提取 MCP 工具的输出 Schema。"""
        output_schema = getattr(tool, "output_schema", None)
        if isinstance(output_schema, dict):
            return output_schema
        return None

    def build_mcp_code(self, code_prefix: str | None, tool_name: str) -> str:
        """根据可选前缀和 MCP 原始工具名生成平台 MCP 工具编码。"""
        cleaned_name = tool_name.strip()
        if code_prefix:
            return f"{code_prefix.strip()}.{cleaned_name}"
        return cleaned_name

    def to_tool_view(self, record: AgentMCPToolRecord) -> AgentMCPToolView:
        """把 MCP 工具数据库模型转换为接口视图。"""
        return AgentMCPToolView(
            id=record.id,
            mcp_code=record.mcp_code,
            name=record.name,
            description=record.description,
            base_url=record.base_url,
            transport=record.transport,
            auth_type=record.auth_type,
            auth_config=record.auth_config,
            input_schema=record.input_schema,
            output_schema=record.output_schema,
            status=record.status,
            created_at=record.created_at.isoformat() if record.created_at else None,
            updated_at=record.updated_at.isoformat() if record.updated_at else None,
        )
