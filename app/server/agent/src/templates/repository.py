from datetime import datetime

from sqlalchemy import func, or_
from sqlmodel import Session, col, select

from app.server.agent.src.templates.models import AgentTemplate


class AgentTemplateRepository:
    """Agent 模板数据访问层，负责读写 agent.agent_templates。"""

    def get_by_agent_id(self, db: Session, agent_id: str) -> AgentTemplate | None:
        """
        根据 agent_id 查询 Agent 模板。

        Args:
            db: 数据库会话。
            agent_id: Agent 稳定业务 ID。

        Returns:
            匹配到的模板；不存在时返回 None。
        """
        sql = select(AgentTemplate).where(AgentTemplate.agent_id == agent_id)
        return db.exec(sql).first()

    def save(self, db: Session, template: AgentTemplate) -> AgentTemplate:
        """
        保存 Agent 模板。

        Args:
            db: 数据库会话。
            template: 待保存的模板模型。

        Returns:
            已刷新到当前事务的模板模型。
        """
        db.add(template)
        # Repository 不提交事务，确保模板相关的组合操作可以由 Service 整体回滚。
        db.flush()
        db.refresh(template)
        return template

    def upsert(
        self,
        db: Session,
        *,
        agent_id: str,
        agent_name: str,
        description: str | None,
        config: dict,
        status: str,
    ) -> AgentTemplate:
        """
        按 agent_id 创建或更新 Agent 模板。

        Args:
            db: 数据库会话。
            agent_id: Agent 稳定业务 ID。
            agent_name: Agent 展示名称。
            description: Agent 模板描述。
            config: Agent 模板配置。
            status: 模板状态。

        Returns:
            创建或更新后的模板模型。
        """
        template = self.get_by_agent_id(db, agent_id)
        if template is None:
            template = AgentTemplate(
                agent_id=agent_id,
                agent_name=agent_name,
                description=description,
                config=config,
                status=status,
            )
            return self.save(db, template)

        template.agent_name = agent_name
        template.description = description
        template.config = config
        template.status = status
        template.updated_at = datetime.now()
        return self.save(db, template)

    def list_templates(
        self,
        db: Session,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[AgentTemplate], int]:
        """
        分页查询 Agent 模板列表。

        Args:
            db: 数据库会话。
            keyword: 关键字，匹配 agent_id、agent_name、description。
            status: 模板状态。
            page: 页码。
            page_size: 每页数量。

        Returns:
            模板列表和总数量。
        """
        filters = []
        if keyword:
            like_keyword = f"%{keyword.strip()}%"
            filters.append(
                or_(
                    col(AgentTemplate.agent_id).ilike(like_keyword),
                    col(AgentTemplate.agent_name).ilike(like_keyword),
                    col(AgentTemplate.description).ilike(like_keyword),
                )
            )
        if status:
            filters.append(AgentTemplate.status == status)

        base_sql = select(AgentTemplate)
        count_sql = select(func.count()).select_from(AgentTemplate)
        for query_filter in filters:
            base_sql = base_sql.where(query_filter)
            count_sql = count_sql.where(query_filter)

        # 模板管理页通常关心最近修改的模板，所以按 updated_at 倒序展示。
        offset = (page - 1) * page_size
        list_sql = base_sql.order_by(AgentTemplate.updated_at.desc()).offset(offset).limit(page_size)
        rows = list(db.exec(list_sql).all())
        total = db.exec(count_sql).one()
        return rows, int(total)

    def delete_by_agent_ids(self, db: Session, agent_ids: list[str]) -> int:
        """
        根据 agent_id 列表批量删除 Agent 模板。

        Args:
            db: 数据库会话。
            agent_ids: 待删除的 Agent 稳定业务 ID 列表。

        Returns:
            实际删除的记录数量。
        """
        if not agent_ids:
            return 0
        # 过滤掉空字符串，避免 SQL 出现 agent_id = '' 的无意义匹配。
        normalized_ids = [agent_id for agent_id in agent_ids if agent_id]
        if not normalized_ids:
            return 0
        existing = db.exec(
            select(AgentTemplate).where(col(AgentTemplate.agent_id).in_(normalized_ids))
        ).all()
        for template in existing:
            db.delete(template)
        db.flush()
        return len(existing)
