from sqlmodel import Session

from app.server.agent.src.model.models import ModelConfigRecord
from app.server.agent.src.model.repository import ModelConfigRepository
from app.server.agent.src.model.schemas import (
    ModelConfigDeleteRequest,
    ModelConfigSearchRequest,
    ModelConfigSearchResponse,
    ModelConfigUpsertRequest,
    ModelConfigView,
)


class ModelConfigService:
    """模型配置服务，负责模型资源池的增删改查和运行时校验。"""

    def __init__(self, repository: ModelConfigRepository | None = None):
        """初始化模型配置服务。"""
        self.repository = repository or ModelConfigRepository()

    def upsert_model(self, db: Session, request: ModelConfigUpsertRequest) -> ModelConfigView:
        """新增或更新模型配置。"""
        record = self.repository.upsert(
            db,
            model_code=request.model_code,
            original_model_code=request.original_model_code,
            model_name=request.model_name,
            model_type=request.model_type,
            base_url=request.base_url,
            api_key=request.api_key,
            api_type=request.api_type,
            support_stream=request.support_stream,
            support_tool_calling=request.support_tool_calling,
            support_structured_output=request.support_structured_output,
            is_multimodal=request.is_multimodal,
            enabled=request.enabled,
            extra_config=request.extra_config,
            description=request.description,
        )
        return self.to_view(record)

    def get_model(self, db: Session, model_code: str) -> ModelConfigView | None:
        """查询单个模型配置视图。"""
        record = self.repository.get_by_model_code(db, model_code)
        return self.to_view(record) if record else None

    def require_enabled_model(
        self,
        db: Session,
        model_code: str,
        model_type: str,
    ) -> ModelConfigRecord:
        """校验并返回指定编码、指定类型的已启用模型。"""
        record = self.repository.get_enabled_by_code_and_type(db, model_code, model_type)
        if record is None:
            raise RuntimeError(f"模型 {model_code} 不存在、未启用，或不是 {model_type} 类型")
        return record

    def search_models(self, db: Session, request: ModelConfigSearchRequest) -> ModelConfigSearchResponse:
        """分页查询模型配置列表。"""
        rows, total = self.repository.list_configs(
            db,
            keyword=request.keyword,
            model_type=request.model_type,
            enabled=request.enabled,
            page=request.page,
            page_size=request.page_size,
        )
        return ModelConfigSearchResponse(
            total=total,
            page=request.page,
            page_size=request.page_size,
            items=[self.to_view(row) for row in rows],
        )

    def delete_models(self, db: Session, request: ModelConfigDeleteRequest) -> int:
        """批量删除模型配置。"""
        return self.repository.delete_by_model_codes(db, request.model_codes)

    def require_enabled_chat_model(self, db: Session, model_code: str | None) -> ModelConfigRecord:
        """校验并返回可用于 Agent 的已启用 chat 模型配置。"""
        if not model_code:
            raise RuntimeError("Agent 模板必须配置 runtime_options.model_code")
        record = self.repository.get_enabled_chat_by_code(db, model_code)
        if record is None:
            raise RuntimeError(f"模型 {model_code} 不存在、未启用，或不是 chat 类型")
        if not record.api_key:
            raise RuntimeError(f"模型 {model_code} 未配置 api_key")
        return record

    def to_view(self, record: ModelConfigRecord) -> ModelConfigView:
        """把数据库模型转换为接口返回视图，并返回本地配置中的 API Key。"""
        return ModelConfigView(
            id=record.id,
            model_code=record.model_code,
            model_name=record.model_name,
            model_type=record.model_type,
            base_url=record.base_url,
            api_key=record.api_key,
            api_type=record.api_type,
            support_stream=record.support_stream,
            support_tool_calling=record.support_tool_calling,
            support_structured_output=record.support_structured_output,
            is_multimodal=record.is_multimodal,
            enabled=record.enabled,
            extra_config=record.extra_config,
            description=record.description,
            created_at=record.created_at.isoformat() if record.created_at else None,
            updated_at=record.updated_at.isoformat() if record.updated_at else None,
        )
