from datetime import datetime
from typing import Any

from sqlmodel import Session, func, or_, select

from app.server.agent.src.runs.models import AgentRun
from app.server.agent.src.runs.schemas import AgentRunSearchRequest, AgentRunSearchResponse, AgentRunView


class AgentRunService:
    """Agent 运行记录服务。

    该服务记录一次 Agent 运行的业务台账，和 LangSmith 的链路监控互补。
    同一张 agent_runs 表同时承载主 Agent 和 A2A 子 Agent，避免运行链路散落在多张表里。
    """

    def create_running(
        self,
        db: Session,
        *,
        run_id: str,
        query: str,
        run_type: str = "main",
        parent_run_id: str | None = None,
        agent_id: str | None = None,
        conversation_id: str | None = None,
        user_message_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AgentRun:
        """创建一条 running 状态的 Agent 运行记录。

        Args:
            db: PostgreSQL Session。
            run_id: 本次 Agent 运行 ID，同时也是 agent_runs 主键。
            query: 本次运行的用户输入或子任务输入。
            run_type: 运行类型，main=主 Agent，sub=A2A 子 Agent。
            parent_run_id: 父级 Agent 运行 ID；主 Agent 为空，子 Agent 用它关联主 Agent。
            agent_id: 当前运行的 Agent 模板 ID；没有模板时为空。
            conversation_id: 用户会话 ID；子 Agent 记录父级会话 ID，便于按会话查询完整运行链路。
            user_message_id: 本次主 Agent 运行对应的用户消息 ID；子 Agent 通常为空。
            metadata: 扩展元数据，例如工具列表、A2A 白名单等。

        Returns:
            已持久化的 AgentRun 记录。
        """
        row = AgentRun(
            run_id=run_id,
            run_type=run_type,
            parent_run_id=parent_run_id,
            agent_id=agent_id,
            conversation_id=conversation_id,
            user_message_id=user_message_id,
            query=query,
            status="running",
            extra_metadata=metadata or {},
        )
        db.add(row)
        # 运行记录会和同阶段的会话、消息一起提交，避免阶段内出现部分成功。
        db.flush()
        db.refresh(row)
        return row

    def mark_success(
        self,
        db: Session,
        *,
        run_id: str,
        answer: str,
        assistant_message_id: str | None = None,
        elapsed_ms: float,
    ) -> AgentRun | None:
        """把 Agent 运行记录标记为成功。

        Args:
            db: PostgreSQL Session。
            run_id: 本次 Agent 运行 ID。
            answer: Agent 最终回答文本。
            assistant_message_id: 本次主 Agent 运行对应的助手消息 ID；子 Agent 通常为空。
            elapsed_ms: 本次运行总耗时，单位毫秒。

        Returns:
            更新后的 AgentRun；记录不存在时返回 None。
        """
        row = self.get_by_run_id(db, run_id)
        if row is None:
            return None
        row.status = "success"
        row.answer = answer
        row.assistant_message_id = assistant_message_id
        row.error_message = None
        row.elapsed_ms = elapsed_ms
        row.finished_at = datetime.now()
        db.add(row)
        db.flush()
        db.refresh(row)
        return row

    def mark_failed(self, db: Session, *, run_id: str, error_message: str, elapsed_ms: float) -> AgentRun | None:
        """把 Agent 运行记录标记为失败。

        Args:
            db: PostgreSQL Session。
            run_id: 本次 Agent 运行 ID。
            error_message: 失败原因。
            elapsed_ms: 本次运行失败前耗时，单位毫秒。

        Returns:
            更新后的 AgentRun；记录不存在时返回 None。
        """
        row = self.get_by_run_id(db, run_id)
        if row is None:
            return None
        row.status = "failed"
        row.error_message = error_message
        row.elapsed_ms = elapsed_ms
        row.finished_at = datetime.now()
        db.add(row)
        db.flush()
        db.refresh(row)
        return row

    def mark_interrupted(
        self,
        db: Session,
        *,
        run_id: str,
        interrupt_type: str | None = None,
        interrupt_payload: dict[str, Any] | None = None,
        elapsed_ms: float,
    ) -> AgentRun | None:
        """把 Agent 运行记录标记为中断等待用户输入。

        Args:
            db: PostgreSQL Session。
            run_id: 本次 Agent 运行 ID。
            interrupt_type: 中断类型，例如 plan_confirmation。
            interrupt_payload: 返回给前端的中断 payload。
            elapsed_ms: 中断发生前耗时，单位毫秒。

        Returns:
            更新后的 AgentRun；记录不存在时返回 None。
        """
        row = self.get_by_run_id(db, run_id)
        if row is None:
            return None
        metadata = dict(row.extra_metadata or {})
        metadata["interrupt_type"] = interrupt_type
        metadata["interrupt_payload"] = interrupt_payload or {}
        row.status = "interrupted"
        row.error_message = None
        row.elapsed_ms = elapsed_ms
        row.extra_metadata = metadata
        db.add(row)
        db.flush()
        db.refresh(row)
        return row


    def _to_view(self, row: AgentRun) -> AgentRunView:
        """把数据库运行记录模型转换为接口返回视图。

        Args:
            row: AgentRun 数据库模型。

        Returns:
            可直接返回给接口调用方的 AgentRunView。
        """
        return AgentRunView(
            run_id=row.run_id,
            run_type=row.run_type,
            parent_run_id=row.parent_run_id,
            agent_id=row.agent_id,
            conversation_id=row.conversation_id,
            user_message_id=row.user_message_id,
            assistant_message_id=row.assistant_message_id,
            query=row.query,
            answer=row.answer,
            status=row.status,
            error_message=row.error_message,
            elapsed_ms=row.elapsed_ms,
            metadata=row.extra_metadata,
            started_at=row.started_at.isoformat() if row.started_at else None,
            finished_at=row.finished_at.isoformat() if row.finished_at else None,
        )

    def search_runs(self, db: Session, request: AgentRunSearchRequest) -> AgentRunSearchResponse:
        """分页查询 Agent 运行记录。

        Args:
            db: PostgreSQL Session。
            request: 查询条件和分页参数。

        Returns:
            Agent 运行记录分页响应。
        """
        conditions = []
        if request.run_id:
            conditions.append(AgentRun.run_id == request.run_id.strip())
        if request.run_type:
            conditions.append(AgentRun.run_type == request.run_type)
        if request.parent_run_id:
            conditions.append(AgentRun.parent_run_id == request.parent_run_id.strip())
        if request.agent_id:
            conditions.append(AgentRun.agent_id == request.agent_id.strip())
        if request.conversation_id:
            conditions.append(AgentRun.conversation_id == request.conversation_id.strip())
        if request.status:
            conditions.append(AgentRun.status == request.status.strip())

        base_sql = select(AgentRun)
        count_sql = select(func.count()).select_from(AgentRun)
        if conditions:
            base_sql = base_sql.where(*conditions)
            count_sql = count_sql.where(*conditions)

        offset = (request.page - 1) * request.page_size
        rows = db.exec(
            base_sql.order_by(AgentRun.started_at.desc()).offset(offset).limit(request.page_size)
        ).all()
        total = db.exec(count_sql).one()

        return AgentRunSearchResponse(
            total=total,
            page=request.page,
            page_size=request.page_size,
            items=[self._to_view(row) for row in rows],
        )

    def get_run_view(self, db: Session, run_id: str) -> AgentRunView | None:
        """根据 run_id 查询 Agent 运行记录视图。

        Args:
            db: PostgreSQL Session。
            run_id: 本次 Agent 运行 ID。

        Returns:
            匹配的运行记录视图；不存在时返回 None。
        """
        row = self.get_by_run_id(db, run_id)
        return self._to_view(row) if row else None

    def list_run_chain(self, db: Session, run_id: str) -> list[AgentRunView]:
        """查询某次主 Agent 运行及其触发的子 Agent 运行。

        Args:
            db: PostgreSQL Session。
            run_id: 主 Agent 运行 ID。

        Returns:
            主运行和子运行记录列表，按开始时间升序排列。
        """
        sql = (
            select(AgentRun)
            .where(or_(AgentRun.run_id == run_id, AgentRun.parent_run_id == run_id))
            .order_by(AgentRun.started_at.asc())
        )
        rows = db.exec(sql).all()
        return [self._to_view(row) for row in rows]

    def get_latest_interrupted_by_conversation(self, db: Session, conversation_id: str) -> AgentRun | None:
        """查询某个会话中最新的待恢复主 Agent 运行。

        Args:
            db: PostgreSQL Session。
            conversation_id: 会话 ID。

        Returns:
            最新的 interrupted 状态主运行；不存在时返回 None。
        """
        cleaned_conversation_id = conversation_id.strip()
        if not cleaned_conversation_id:
            return None

        sql = (
            select(AgentRun)
            .where(
                AgentRun.conversation_id == cleaned_conversation_id,
                AgentRun.run_type == "main",
                AgentRun.status == "interrupted",
            )
            .order_by(AgentRun.started_at.desc())
        )
        return db.exec(sql).first()

    def get_by_run_id(self, db: Session, run_id: str) -> AgentRun | None:
        """根据 run_id 查询 Agent 运行记录。

        Args:
            db: PostgreSQL Session。
            run_id: 本次 Agent 运行 ID。

        Returns:
            匹配的 AgentRun；不存在时返回 None。
        """
        sql = select(AgentRun).where(AgentRun.run_id == run_id)
        return db.exec(sql).first()
