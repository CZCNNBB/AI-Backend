"""业务平台及资源绑定的数据访问层。"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import delete, func, or_
from sqlmodel import Session, col, select

from app.server.platform.src.models import (
    BusinessPlatform,
    BusinessPlatformAgent,
    BusinessPlatformAPIKey,
    BusinessPlatformMCPTool,
)

if TYPE_CHECKING:
    from app.server.agent.src.templates.models import AgentTemplate
    from app.server.fastmcp.src.models import MCPToolRecord


class BusinessPlatformRepository:
    """封装业务平台、API Key 与资源绑定的数据库操作。"""

    def get_platform_by_id(self, db: Session, platform_id: int) -> BusinessPlatform | None:
        """根据数据库主键查询业务平台。"""
        return db.get(BusinessPlatform, platform_id)

    def get_platform_by_code(self, db: Session, platform_code: str) -> BusinessPlatform | None:
        """根据稳定平台编码查询业务平台。"""
        sql = select(BusinessPlatform).where(BusinessPlatform.platform_code == platform_code)
        return db.exec(sql).first()

    def list_platforms(
        self,
        db: Session,
        *,
        keyword: str | None,
        status: str | None,
        page: int,
        page_size: int,
    ) -> tuple[list[BusinessPlatform], int]:
        """按管理端查询条件分页读取业务平台。"""
        conditions = []
        if keyword:
            like_keyword = f"%{keyword.strip()}%"
            conditions.append(
                or_(
                    col(BusinessPlatform.platform_code).ilike(like_keyword),
                    col(BusinessPlatform.platform_name).ilike(like_keyword),
                    col(BusinessPlatform.description).ilike(like_keyword),
                )
            )
        if status:
            conditions.append(BusinessPlatform.status == status)

        data_sql = select(BusinessPlatform)
        count_sql = select(func.count()).select_from(BusinessPlatform)
        if conditions:
            data_sql = data_sql.where(*conditions)
            count_sql = count_sql.where(*conditions)

        offset = (page - 1) * page_size
        rows = db.exec(
            data_sql.order_by(BusinessPlatform.updated_at.desc()).offset(offset).limit(page_size)
        ).all()
        total = db.exec(count_sql).one()
        return list(rows), int(total)

    def save_platform(self, db: Session, platform: BusinessPlatform) -> BusinessPlatform:
        """保存业务平台并刷新数据库生成字段，事务提交由接口边界负责。"""
        db.add(platform)
        db.flush()
        db.refresh(platform)
        return platform

    def get_api_key_by_hash(self, db: Session, key_hash: str) -> BusinessPlatformAPIKey | None:
        """根据完整密钥摘要查询平台 API Key 记录。"""
        sql = select(BusinessPlatformAPIKey).where(BusinessPlatformAPIKey.key_hash == key_hash)
        return db.exec(sql).first()

    def get_api_key_by_name(
        self,
        db: Session,
        *,
        platform_id: int,
        key_name: str,
    ) -> BusinessPlatformAPIKey | None:
        """根据平台和用途名称查询已有 API Key。"""
        sql = select(BusinessPlatformAPIKey).where(
            BusinessPlatformAPIKey.platform_id == platform_id,
            BusinessPlatformAPIKey.key_name == key_name,
        )
        return db.exec(sql).first()

    def save_api_key(self, db: Session, api_key: BusinessPlatformAPIKey) -> BusinessPlatformAPIKey:
        """保存平台 API Key 记录并刷新数据库生成字段。"""
        db.add(api_key)
        db.flush()
        db.refresh(api_key)
        return api_key

    def get_api_key_by_id(self, db: Session, api_key_id: int) -> BusinessPlatformAPIKey | None:
        """根据主键查询平台 API Key。"""
        return db.get(BusinessPlatformAPIKey, api_key_id)

    def list_api_keys_for_platform(
        self,
        db: Session,
        platform_id: int,
    ) -> list[BusinessPlatformAPIKey]:
        """查询业务平台签发过的全部 API Key，按创建时间倒序返回。"""
        sql = (
            select(BusinessPlatformAPIKey)
            .where(BusinessPlatformAPIKey.platform_id == platform_id)
            .order_by(BusinessPlatformAPIKey.created_at.desc())
        )
        return list(db.exec(sql).all())

    def get_default_api_key_for_platform(
        self,
        db: Session,
        platform_id: int,
    ) -> BusinessPlatformAPIKey | None:
        """查询平台最近更新且仍处于可用状态的默认调试 API Key。"""
        current_time = datetime.now()
        sql = (
            select(BusinessPlatformAPIKey)
            .where(
                BusinessPlatformAPIKey.platform_id == platform_id,
                BusinessPlatformAPIKey.status == "enabled",
                or_(
                    BusinessPlatformAPIKey.expires_at.is_(None),
                    BusinessPlatformAPIKey.expires_at > current_time,
                ),
            )
            .order_by(BusinessPlatformAPIKey.updated_at.desc())
        )
        return db.exec(sql).first()

    def list_platforms_for_agent(self, db: Session, agent_id: str) -> list[BusinessPlatform]:
        """查询 Agent 绑定的全部启用业务平台。"""
        # 延迟导入 Agent ORM，避免 platform 与 AgentTemplateService 形成循环依赖。
        from app.server.agent.src.templates.models import AgentTemplate

        sql = (
            select(BusinessPlatform)
            .join(BusinessPlatformAgent, BusinessPlatformAgent.platform_id == BusinessPlatform.id)
            .join(AgentTemplate, AgentTemplate.id == BusinessPlatformAgent.agent_template_id)
            .where(
                AgentTemplate.agent_id == agent_id,
                BusinessPlatform.status == "enabled",
            )
            .order_by(BusinessPlatform.platform_name.asc())
        )
        return list(db.exec(sql).all())

    def get_platform_ids_for_agent(self, db: Session, agent_template_id: int) -> list[int]:
        """查询一个 Agent 模板绑定的全部业务平台 ID。"""
        sql = select(BusinessPlatformAgent.platform_id).where(
            BusinessPlatformAgent.agent_template_id == agent_template_id
        )
        return [int(platform_id) for platform_id in db.exec(sql).all()]

    def get_platform_ids_for_tool(self, db: Session, mcp_tool_id: int) -> list[int]:
        """查询一个 MCP Tool 绑定的全部业务平台 ID。"""
        sql = select(BusinessPlatformMCPTool.platform_id).where(
            BusinessPlatformMCPTool.mcp_tool_id == mcp_tool_id
        )
        return [int(platform_id) for platform_id in db.exec(sql).all()]

    def replace_agent_platforms(
        self,
        db: Session,
        *,
        agent_template_id: int,
        platform_ids: list[int],
    ) -> None:
        """使用新集合完整替换 Agent 模板的平台绑定。"""
        db.exec(
            delete(BusinessPlatformAgent).where(
                BusinessPlatformAgent.agent_template_id == agent_template_id
            )
        )
        for platform_id in platform_ids:
            db.add(
                BusinessPlatformAgent(
                    platform_id=platform_id,
                    agent_template_id=agent_template_id,
                )
            )
        db.flush()

    def replace_tool_platforms(
        self,
        db: Session,
        *,
        mcp_tool_id: int,
        platform_ids: list[int],
    ) -> None:
        """使用新集合完整替换 MCP Tool 的平台绑定。"""
        db.exec(
            delete(BusinessPlatformMCPTool).where(
                BusinessPlatformMCPTool.mcp_tool_id == mcp_tool_id
            )
        )
        for platform_id in platform_ids:
            db.add(BusinessPlatformMCPTool(platform_id=platform_id, mcp_tool_id=mcp_tool_id))
        db.flush()

    def list_existing_platform_ids(self, db: Session, platform_ids: list[int]) -> set[int]:
        """返回请求集合中数据库真实存在的平台 ID。"""
        if not platform_ids:
            return set()
        sql = select(BusinessPlatform.id).where(col(BusinessPlatform.id).in_(platform_ids))
        return {int(platform_id) for platform_id in db.exec(sql).all()}

    def is_agent_bound_to_platform(self, db: Session, *, agent_id: str, platform_id: int) -> bool:
        """判断指定业务平台是否绑定了目标 Agent。"""
        # 延迟导入 Agent ORM，避免 platform 基础模块与 AgentTemplateService 形成循环依赖。
        from app.server.agent.src.templates.models import AgentTemplate

        sql = (
            select(func.count())
            .select_from(BusinessPlatformAgent)
            .join(AgentTemplate, AgentTemplate.id == BusinessPlatformAgent.agent_template_id)
            .where(
                AgentTemplate.agent_id == agent_id,
                BusinessPlatformAgent.platform_id == platform_id,
            )
        )
        return int(db.exec(sql).one()) > 0

    def get_tool_platform_ids_by_names(self, db: Session, tool_names: list[str]) -> dict[str, set[int]]:
        """批量查询 MCP Tool 名称对应的平台绑定集合。"""
        if not tool_names:
            return {}
        # 延迟导入 MCP ORM，保证 FastMCPService 可以安全依赖 platform service。
        from app.server.fastmcp.src.models import MCPToolRecord

        sql = (
            select(MCPToolRecord.name, BusinessPlatformMCPTool.platform_id)
            .join(BusinessPlatformMCPTool, BusinessPlatformMCPTool.mcp_tool_id == MCPToolRecord.id)
            .where(col(MCPToolRecord.name).in_(tool_names))
        )
        result: dict[str, set[int]] = {tool_name: set() for tool_name in tool_names}
        for tool_name, platform_id in db.exec(sql).all():
            result.setdefault(str(tool_name), set()).add(int(platform_id))
        return result

    def list_eligible_mcp_tools(
        self,
        db: Session,
        platform_ids: list[int],
    ) -> list[MCPToolRecord]:
        """查询平台绑定集合完全覆盖目标集合的已发布 MCP Tool。"""
        if not platform_ids:
            return []
        from app.server.fastmcp.src.models import MCPToolRecord

        required_platform_ids = set(platform_ids)
        rows = db.exec(
            select(MCPToolRecord)
            .where(MCPToolRecord.status == "enabled")
            .order_by(MCPToolRecord.name.asc())
        ).all()
        eligible_tools: list[MCPToolRecord] = []
        for tool in rows:
            if tool.id is None:
                continue
            bound_platform_ids = set(self.get_platform_ids_for_tool(db, tool.id))
            if required_platform_ids.issubset(bound_platform_ids):
                eligible_tools.append(tool)
        return eligible_tools

    def list_agent_templates_using_tool(
        self,
        db: Session,
        tool_name: str,
    ) -> list[AgentTemplate]:
        """查询 config.tools 中引用指定 MCP Tool 的 Agent 模板。"""
        from app.server.agent.src.templates.models import AgentTemplate

        templates = db.exec(select(AgentTemplate)).all()
        matched_templates: list[AgentTemplate] = []
        for template in templates:
            config = dict(template.config or {})
            configured_tools = config.get("tools")
            if isinstance(configured_tools, list) and tool_name in configured_tools:
                matched_templates.append(template)
        return matched_templates
