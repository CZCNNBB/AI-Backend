from datetime import datetime

from sqlalchemy import func, or_
from sqlmodel import Session, col, select

from app.server.fastmcp.src.models import MCPToolRecord


class MCPToolRepository:
    """HTTP API 转换型 MCP Tool 数据访问层。"""

    def get_tool_by_name(self, db: Session, name: str) -> MCPToolRecord | None:
        """根据 MCP Tool 名称查询单条配置。"""
        sql = select(MCPToolRecord).where(MCPToolRecord.name == name)
        return db.exec(sql).first()

    def save_tool(self, db: Session, record: MCPToolRecord) -> MCPToolRecord:
        """暂存工具配置并刷新生成字段，事务提交由外层统一负责。"""
        db.add(record)
        db.flush()
        db.refresh(record)
        return record

    def upsert_tool(
        self,
        db: Session,
        *,
        name: str,
        description: str | None,
        api_url: str,
        http_method: str,
        static_headers: dict,
        parameters: list[dict],
        business_token_header: str | None,
        input_schema: dict,
        output_schema: dict | None,
        timeout_seconds: float,
        status: str,
    ) -> MCPToolRecord:
        """按工具名新增或覆盖 HTTP API 转换配置。"""
        record = self.get_tool_by_name(db, name)
        if record is None:
            record = MCPToolRecord(name=name, api_url=api_url)

        record.name = name
        record.description = description
        record.api_url = api_url
        record.http_method = http_method
        record.static_headers = static_headers
        record.parameters = parameters
        record.business_token_header = business_token_header
        record.input_schema = input_schema
        record.output_schema = output_schema
        record.timeout_seconds = timeout_seconds
        record.status = status
        record.updated_at = datetime.now()
        return self.save_tool(db, record)

    def update_status(self, db: Session, record: MCPToolRecord, status: str) -> MCPToolRecord:
        """更新工具发布状态并刷新数据库记录。"""
        record.status = status
        record.updated_at = datetime.now()
        return self.save_tool(db, record)

    def list_tools(
        self,
        db: Session,
        *,
        keyword: str | None = None,
        platform_id: int | None = None,
        status: str | None = None,
        api_url: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[MCPToolRecord], int]:
        """分页查询 MCP Tool 配置。"""
        # 延迟导入平台关联表，避免 FastMCP 基础模型与 platform 模块形成顶层循环依赖。
        from app.server.platform.src.models import BusinessPlatformMCPTool

        filters = []
        if keyword:
            like_keyword = f"%{keyword}%"
            filters.append(
                or_(
                    col(MCPToolRecord.name).ilike(like_keyword),
                    col(MCPToolRecord.description).ilike(like_keyword),
                    col(MCPToolRecord.api_url).ilike(like_keyword),
                )
            )
        if status:
            filters.append(MCPToolRecord.status == status)
        if api_url:
            filters.append(MCPToolRecord.api_url == api_url)

        data_sql = select(MCPToolRecord)
        count_sql = select(func.count()).select_from(MCPToolRecord)
        if platform_id is not None:
            # 关联表对 platform_id + mcp_tool_id 有联合主键，因此按单个平台过滤不会产生重复工具行。
            data_sql = data_sql.join(
                BusinessPlatformMCPTool,
                BusinessPlatformMCPTool.mcp_tool_id == MCPToolRecord.id,
            ).where(BusinessPlatformMCPTool.platform_id == platform_id)
            count_sql = count_sql.join(
                BusinessPlatformMCPTool,
                BusinessPlatformMCPTool.mcp_tool_id == MCPToolRecord.id,
            ).where(BusinessPlatformMCPTool.platform_id == platform_id)
        for query_filter in filters:
            data_sql = data_sql.where(query_filter)
            count_sql = count_sql.where(query_filter)

        offset = (page - 1) * page_size
        rows = db.exec(data_sql.order_by(MCPToolRecord.updated_at.desc()).offset(offset).limit(page_size)).all()
        total = db.exec(count_sql).one()
        return list(rows), int(total)

    def list_enabled_tools(self, db: Session) -> list[MCPToolRecord]:
        """查询全部已发布工具，供 FastMCP Registry 启动加载。"""
        sql = select(MCPToolRecord).where(MCPToolRecord.status == "enabled")
        return list(db.exec(sql).all())

    def list_enabled_tools_by_names(self, db: Session, tool_names: list[str]) -> list[MCPToolRecord]:
        """查询 Agent 指定的已发布 MCP Tool 配置。"""
        if not tool_names:
            return []
        sql = select(MCPToolRecord).where(
            col(MCPToolRecord.name).in_(tool_names),
            MCPToolRecord.status == "enabled",
        )
        return list(db.exec(sql).all())

    def delete_tools_by_names(self, db: Session, tool_names: list[str]) -> int:
        """批量删除工具配置；提交由接口事务边界负责。"""
        if not tool_names:
            return 0
        tools = db.exec(select(MCPToolRecord).where(col(MCPToolRecord.name).in_(tool_names))).all()
        for tool in tools:
            db.delete(tool)
        db.flush()
        return len(tools)
