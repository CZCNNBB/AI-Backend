from sqlmodel import Session

from app.server.agent.src.model import ModelConfigService
from app.server.agent.src.templates.models import AgentTemplate
from app.server.agent.src.templates.repository import AgentTemplateRepository
from app.server.agent.src.templates.schemas import (
    AgentTemplateDeleteRequest,
    AgentTemplateSearchRequest,
    AgentTemplateSearchResponse,
    AgentTemplateUpsertRequest,
    AgentTemplateView,
)
from app.server.platform.src.service import BusinessPlatformService


class AgentTemplateService:
    """Agent 模板服务，负责模板的创建、更新、查询和删除。"""

    def __init__(
        self,
        repository: AgentTemplateRepository | None = None,
        model_config_service: ModelConfigService | None = None,
        platform_service: BusinessPlatformService | None = None,
    ):
        """初始化 Agent 模板服务。"""
        self.repository = repository or AgentTemplateRepository()
        self.model_config_service = model_config_service or ModelConfigService()
        self.platform_service = platform_service or BusinessPlatformService()

    def upsert_template(self, db: Session, request: AgentTemplateUpsertRequest) -> AgentTemplateView:
        """创建或更新 Agent 模板，并校验模板绑定的 chat 模型。"""
        model_code = request.config.runtime_options.model_code
        # Agent 模板必须显式绑定一个已启用的 chat 模型，避免误用所谓默认模型。
        self.model_config_service.require_enabled_chat_model(db, model_code)

        # 平台与工具的合法性在配置保存阶段一次性完成。运行组装阶段只读取已经
        # 保存的 config.tools，不再重复执行平台过滤。
        platform_ids = self.platform_service.validate_platform_ids(db, request.platform_ids)
        self.platform_service.validate_agent_tool_platforms(
            db,
            platform_ids=platform_ids,
            tool_names=request.config.tools,
        )

        template = self.repository.upsert(
            db,
            agent_id=request.agent_id,
            agent_name=request.agent_name,
            description=request.description,
            config=self._clean_template_config(request.config.model_dump(mode="json")),
            status=request.status,
        )
        if template.id is None:
            raise RuntimeError("Agent 模板保存后缺少数据库主键")
        self.platform_service.replace_agent_platforms(
            db,
            agent_template_id=template.id,
            platform_ids=platform_ids,
        )
        return self.to_view(template, platform_ids=platform_ids)

    def _clean_template_config(self, config: dict) -> dict:
        """清理模板中已经废弃或只属于单次运行的字段。"""
        cleaned_config = dict(config or {})
        # 清理旧版结构化输出字段，避免历史 JSONB 配置继续向外返回。
        deprecated_schema_key = "response_" + "format"
        cleaned_config.pop(deprecated_schema_key, None)

        # 知识库访问范围属于单次运行授权，模板只保存 knowledge_enabled 能力开关。
        optional_features = cleaned_config.get("optional_features")
        if isinstance(optional_features, dict):
            cleaned_features = dict(optional_features)
            cleaned_features.pop("knowledge_base_ids", None)
            cleaned_config["optional_features"] = cleaned_features
        return cleaned_config

    def get_template(self, db: Session, agent_id: str) -> AgentTemplateView | None:
        """根据 agent_id 查询 Agent 模板详情。"""
        template = self.repository.get_by_agent_id(db, agent_id)
        if template is None:
            return None
        platform_ids = self._get_template_platform_ids(db, template)
        return self.to_view(template, platform_ids=platform_ids)

    def search_templates(self, db: Session, request: AgentTemplateSearchRequest) -> AgentTemplateSearchResponse:
        """分页查询 Agent 模板列表。"""
        rows, total = self.repository.list_templates(
            db,
            keyword=request.keyword,
            status=request.status,
            page=request.page,
            page_size=request.page_size,
        )
        return AgentTemplateSearchResponse(
            total=total,
            page=request.page,
            page_size=request.page_size,
            items=[self.to_view(row, platform_ids=self._get_template_platform_ids(db, row)) for row in rows],
        )

    def delete_templates(self, db: Session, request: AgentTemplateDeleteRequest) -> int:
        """批量删除 Agent 模板。"""
        return self.repository.delete_by_agent_ids(db, request.agent_ids)

    def _get_template_platform_ids(self, db: Session, template: AgentTemplate) -> list[int]:
        """读取 Agent 模板的平台绑定，并保持稳定升序。"""
        if template.id is None:
            return []
        platform_ids = self.platform_service.repository.get_platform_ids_for_agent(db, template.id)
        return sorted(platform_ids)

    def to_view(self, template: AgentTemplate, *, platform_ids: list[int] | None = None) -> AgentTemplateView:
        """将数据库模型转换为接口响应视图。"""
        return AgentTemplateView(
            agent_id=template.agent_id,
            agent_name=template.agent_name,
            description=template.description,
            platform_ids=list(platform_ids or []),
            config=self._clean_template_config(template.config),
            status=template.status,
            created_at=template.created_at.isoformat() if template.created_at else None,
            updated_at=template.updated_at.isoformat() if template.updated_at else None,
        )
