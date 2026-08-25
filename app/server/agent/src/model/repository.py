from datetime import datetime

from sqlalchemy import func, or_
from sqlmodel import Session, col, select

from app.server.agent.src.model.models import ModelConfigRecord


class ModelConfigRepository:
    """模型配置数据访问层，负责读写 public.model_configs。"""

    def get_by_model_code(self, db: Session, model_code: str) -> ModelConfigRecord | None:
        """根据模型编码查询模型配置。"""
        sql = select(ModelConfigRecord).where(ModelConfigRecord.model_code == model_code)
        return db.exec(sql).first()

    def get_enabled_chat_by_code(self, db: Session, model_code: str) -> ModelConfigRecord | None:
        """查询已启用的 chat 模型，供 Agent 模板校验和运行时使用。"""
        sql = select(ModelConfigRecord).where(
            ModelConfigRecord.model_code == model_code,
            ModelConfigRecord.model_type == "chat",
            ModelConfigRecord.enabled.is_(True),
        )
        return db.exec(sql).first()

    def get_enabled_by_code_and_type(
        self,
        db: Session,
        model_code: str,
        model_type: str,
    ) -> ModelConfigRecord | None:
        """按模型编码和类型查询已启用模型。"""
        sql = select(ModelConfigRecord).where(
            ModelConfigRecord.model_code == model_code,
            ModelConfigRecord.model_type == model_type,
            ModelConfigRecord.enabled.is_(True),
        )
        return db.exec(sql).first()

    def save(self, db: Session, record: ModelConfigRecord) -> ModelConfigRecord:
        """暂存模型配置并刷新数据库生成字段，提交由上层事务边界负责。"""
        db.add(record)
        db.flush()
        db.refresh(record)
        return record

    def list_configs(
        self,
        db: Session,
        *,
        keyword: str | None = None,
        model_type: str | None = None,
        enabled: bool | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[ModelConfigRecord], int]:
        """按条件分页查询模型配置。"""
        filters = []
        if keyword:
            like_keyword = f"%{keyword}%"
            filters.append(
                or_(
                    col(ModelConfigRecord.model_code).ilike(like_keyword),
                    col(ModelConfigRecord.model_name).ilike(like_keyword),
                    col(ModelConfigRecord.description).ilike(like_keyword),
                )
            )
        if model_type:
            filters.append(ModelConfigRecord.model_type == model_type)
        if enabled is not None:
            filters.append(ModelConfigRecord.enabled == enabled)

        base_sql = select(ModelConfigRecord)
        count_sql = select(func.count()).select_from(ModelConfigRecord)
        for query_filter in filters:
            base_sql = base_sql.where(query_filter)
            count_sql = count_sql.where(query_filter)

        offset = (page - 1) * page_size
        rows = db.exec(
            base_sql.order_by(ModelConfigRecord.updated_at.desc()).offset(offset).limit(page_size)
        ).all()
        total = db.exec(count_sql).one()
        return list(rows), int(total)

    def upsert(
        self,
        db: Session,
        *,
        model_code: str,
        original_model_code: str | None,
        model_name: str,
        model_type: str,
        base_url: str,
        api_key: str | None,
        api_type: str,
        support_stream: bool,
        support_tool_calling: bool,
        support_structured_output: bool,
        is_multimodal: bool,
        enabled: bool,
        extra_config: dict | None,
        description: str | None,
    ) -> ModelConfigRecord:
        """按 model_code 新增或更新模型配置。"""
        # Use original_model_code as the lookup key when editing, so model_code itself can be renamed.
        lookup_code = original_model_code or model_code
        record = self.get_by_model_code(db, lookup_code)

        # Avoid silently overwriting another config when the new model_code already exists.
        if record is not None and lookup_code != model_code:
            conflict_record = self.get_by_model_code(db, model_code)
            if conflict_record is not None and conflict_record.id != record.id:
                raise RuntimeError(f"model_code {model_code} already exists")

        if record is None:
            record = ModelConfigRecord(model_code=model_code)
        else:
            record.model_code = model_code

        record.model_name = model_name
        record.model_type = model_type
        record.base_url = base_url
        # api_key is a normal local deployment config value; every save overwrites it.
        record.api_key = api_key
        record.api_type = api_type or "openai_compatible"
        record.support_stream = support_stream
        record.support_tool_calling = support_tool_calling
        record.support_structured_output = support_structured_output
        record.is_multimodal = is_multimodal
        record.enabled = enabled
        record.extra_config = extra_config
        record.description = description
        record.updated_at = datetime.now()
        return self.save(db, record)

    def delete_by_model_codes(self, db: Session, model_codes: list[str]) -> int:
        """根据模型编码列表批量删除模型配置。"""
        normalized_codes = [code for code in model_codes if code]
        if not normalized_codes:
            return 0
        rows = db.exec(
            select(ModelConfigRecord).where(col(ModelConfigRecord.model_code).in_(normalized_codes))
        ).all()
        for row in rows:
            db.delete(row)
        db.flush()
        return len(rows)
