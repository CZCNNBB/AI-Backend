from datetime import datetime

from sqlalchemy import func, or_
from sqlmodel import Session, col, select

from app.server.agent.src.mcp.models import AgentMCPToolRecord


class MCPRepository:
    """MCP 工具数据访问层，负责读写 agent.agent_mcp_tools。"""

    def get_tool_by_code(self, db: Session, mcp_code: str) -> AgentMCPToolRecord | None:
        """根据平台 MCP 工具编码查询单条工具配置。"""
        sql = select(AgentMCPToolRecord).where(AgentMCPToolRecord.mcp_code == mcp_code)
        return db.exec(sql).first()

    def save_tool(self, db: Session, record: AgentMCPToolRecord) -> AgentMCPToolRecord:
        """暂存 MCP 工具配置并刷新数据库生成字段，提交由上层事务边界负责。"""
        db.add(record)
        db.flush()
        db.refresh(record)
        return record

    def upsert_tool(
        self,
        db: Session,
        *,
        mcp_code: str,
        original_mcp_code: str | None = None,
        name: str,
        description: str | None,
        base_url: str,
        transport: str,
        auth_type: str | None,
        auth_config: dict | None,
        input_schema: dict | None,
        output_schema: dict | None,
        status: str,
        overwrite: bool = True,
    ) -> AgentMCPToolRecord:
        """按 MCP 工具编码新增或更新工具配置。"""
        lookup_code = original_mcp_code or mcp_code
        record = self.get_tool_by_code(db, lookup_code)

        if record is not None and lookup_code != mcp_code:
            conflict = self.get_tool_by_code(db, mcp_code)
            if conflict is not None and conflict.id != record.id:
                raise RuntimeError(f"MCP 工具编码已存在: {mcp_code}")

        if record is None:
            record = AgentMCPToolRecord(mcp_code=mcp_code)
        elif not overwrite:
            return record
        else:
            record.mcp_code = mcp_code

        record.name = name
        record.description = description
        record.base_url = base_url
        record.transport = transport
        record.auth_type = auth_type
        record.auth_config = auth_config
        record.input_schema = input_schema
        record.output_schema = output_schema
        record.status = status
        record.updated_at = datetime.now()
        return self.save_tool(db, record)

    def list_tools(
        self,
        db: Session,
        *,
        keyword: str | None = None,
        status: str | None = None,
        base_url: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[AgentMCPToolRecord], int]:
        """分页查询 MCP 工具列表。"""
        filters = []
        if keyword:
            like_keyword = f"%{keyword}%"
            filters.append(
                or_(
                    col(AgentMCPToolRecord.mcp_code).ilike(like_keyword),
                    col(AgentMCPToolRecord.name).ilike(like_keyword),
                    col(AgentMCPToolRecord.description).ilike(like_keyword),
                    col(AgentMCPToolRecord.base_url).ilike(like_keyword),
                )
            )
        if status:
            filters.append(AgentMCPToolRecord.status == status)
        if base_url:
            filters.append(AgentMCPToolRecord.base_url == base_url)

        base_sql = select(AgentMCPToolRecord)
        count_sql = select(func.count()).select_from(AgentMCPToolRecord)
        for query_filter in filters:
            base_sql = base_sql.where(query_filter)
            count_sql = count_sql.where(query_filter)

        offset = (page - 1) * page_size
        rows = db.exec(base_sql.order_by(AgentMCPToolRecord.updated_at.desc()).offset(offset).limit(page_size)).all()
        total = db.exec(count_sql).one()
        return list(rows), int(total)

    def list_enabled_tools_by_codes(self, db: Session, mcp_codes: list[str]) -> list[AgentMCPToolRecord]:
        """根据平台 MCP 工具编码查询已启用工具配置。"""
        if not mcp_codes:
            return []
        sql = select(AgentMCPToolRecord).where(
            col(AgentMCPToolRecord.mcp_code).in_(mcp_codes),
            AgentMCPToolRecord.status == "enabled",
        )
        return list(db.exec(sql).all())

    def delete_tools_by_codes(self, db: Session, mcp_codes: list[str]) -> int:
        """根据平台 MCP 工具编码批量删除工具配置。"""
        normalized_codes = [code for code in mcp_codes if code]
        if not normalized_codes:
            return 0
        tools = db.exec(select(AgentMCPToolRecord).where(col(AgentMCPToolRecord.mcp_code).in_(normalized_codes))).all()
        for tool in tools:
            db.delete(tool)
        db.flush()
        return len(tools)
