"""业务平台管理、API Key 签发和资源绑定服务。"""

from datetime import datetime

from sqlmodel import Session

from app.common.core.exceptions import BusinessException
from app.server.platform.src.models import BusinessPlatform, BusinessPlatformAPIKey
from app.server.platform.src.repository import BusinessPlatformRepository
from app.server.platform.src.schemas import (
    AgentPlatformAccessOption,
    AgentPlatformAccessRequest,
    BusinessPlatformAPIKeyCreateRequest,
    BusinessPlatformAPIKeyCreateResponse,
    BusinessPlatformAPIKeyDisableRequest,
    BusinessPlatformAPIKeyListRequest,
    BusinessPlatformAPIKeyView,
    BusinessPlatformSearchRequest,
    BusinessPlatformSearchResponse,
    BusinessPlatformUpsertRequest,
    BusinessPlatformView,
    PlatformPrincipal,
)
from app.server.platform.src.security import generate_platform_api_key, hash_platform_api_key


class BusinessPlatformService:
    """提供业务平台、平台凭证和资源绑定的业务能力。"""

    def __init__(self, repository: BusinessPlatformRepository | None = None) -> None:
        """初始化业务平台服务。"""
        self.repository = repository or BusinessPlatformRepository()

    def upsert_platform(self, db: Session, request: BusinessPlatformUpsertRequest) -> BusinessPlatformView:
        """按照平台编码创建或更新业务平台。"""
        platform = self.repository.get_platform_by_code(db, request.platform_code)
        if platform is None:
            platform = BusinessPlatform(
                platform_code=request.platform_code,
                platform_name=request.platform_name,
            )

        platform.platform_name = request.platform_name
        platform.description = request.description
        platform.status = request.status
        platform.updated_at = datetime.now()
        saved_platform = self.repository.save_platform(db, platform)
        return self.to_platform_view(saved_platform)

    def get_platform(self, db: Session, platform_code: str) -> BusinessPlatformView | None:
        """根据平台编码获取业务平台视图。"""
        platform = self.repository.get_platform_by_code(db, platform_code)
        return self.to_platform_view(platform) if platform else None

    def search_platforms(
        self,
        db: Session,
        request: BusinessPlatformSearchRequest,
    ) -> BusinessPlatformSearchResponse:
        """分页查询业务平台并转换为接口视图。"""
        rows, total = self.repository.list_platforms(
            db,
            keyword=request.keyword,
            status=request.status,
            page=request.page,
            page_size=request.page_size,
        )
        return BusinessPlatformSearchResponse(
            total=total,
            page=request.page,
            page_size=request.page_size,
            items=[self.to_platform_view(row) for row in rows],
        )

    def create_api_key(
        self,
        db: Session,
        request: BusinessPlatformAPIKeyCreateRequest,
    ) -> BusinessPlatformAPIKeyCreateResponse:
        """为业务平台签发高强度 API Key，并保存明文供内网管理端调试。"""
        platform = self.repository.get_platform_by_code(db, request.platform_code)
        if platform is None or platform.id is None:
            raise BusinessException(code=404, msg=f"业务平台不存在: {request.platform_code}")
        if platform.status != "enabled":
            raise BusinessException(code=400, msg="停用状态的业务平台不能签发 API Key")

        existing_key = self.repository.get_api_key_by_name(
            db,
            platform_id=platform.id,
            key_name=request.key_name,
        )
        if existing_key is not None:
            raise BusinessException(code=409, msg=f"API Key 名称已存在: {request.key_name}")

        plaintext_key, key_prefix = generate_platform_api_key()
        api_key_record = self.repository.save_api_key(
            db,
            BusinessPlatformAPIKey(
                platform_id=platform.id,
                key_name=request.key_name,
                key_prefix=key_prefix,
                api_key=plaintext_key,
                key_hash=hash_platform_api_key(plaintext_key),
                expires_at=request.expires_at,
            ),
        )
        if api_key_record.id is None:
            raise RuntimeError("平台 API Key 保存后缺少数据库主键")
        return BusinessPlatformAPIKeyCreateResponse(
            id=api_key_record.id,
            platform_id=platform.id,
            key_name=api_key_record.key_name,
            key_prefix=api_key_record.key_prefix,
            api_key=plaintext_key,
            expires_at=api_key_record.expires_at.isoformat() if api_key_record.expires_at else None,
        )

    def list_agent_platform_access_options(
        self,
        db: Session,
        request: AgentPlatformAccessRequest,
    ) -> list[AgentPlatformAccessOption]:
        """返回 Agent 绑定的平台及每个平台最近可用的明文调试 Key。"""
        platforms = self.repository.list_platforms_for_agent(db, request.agent_id)
        options: list[AgentPlatformAccessOption] = []
        for platform in platforms:
            if platform.id is None:
                continue

            default_api_key = self.repository.get_default_api_key_for_platform(db, platform.id)
            options.append(
                AgentPlatformAccessOption(
                    platform_id=platform.id,
                    platform_code=platform.platform_code,
                    platform_name=platform.platform_name,
                    api_key_id=default_api_key.id if default_api_key else None,
                    api_key_name=default_api_key.key_name if default_api_key else None,
                    api_key=default_api_key.api_key if default_api_key else None,
                )
            )
        return options

    def list_api_keys(
        self,
        db: Session,
        request: BusinessPlatformAPIKeyListRequest,
    ) -> list[BusinessPlatformAPIKeyView]:
        """查询业务平台全部 API Key，并返回内网管理端需要的完整明文。"""
        platform = self.repository.get_platform_by_code(db, request.platform_code)
        if platform is None or platform.id is None:
            raise BusinessException(code=404, msg=f"业务平台不存在: {request.platform_code}")

        api_keys = self.repository.list_api_keys_for_platform(db, platform.id)
        return [self.to_api_key_view(api_key) for api_key in api_keys]

    def disable_api_key(self, db: Session, request: BusinessPlatformAPIKeyDisableRequest) -> None:
        """停用指定平台 API Key。"""
        api_key_record = self.repository.get_api_key_by_id(db, request.api_key_id)
        if api_key_record is None:
            raise BusinessException(code=404, msg="平台 API Key 不存在")
        api_key_record.status = "disabled"
        api_key_record.updated_at = datetime.now()
        self.repository.save_api_key(db, api_key_record)

    def authenticate_api_key(self, db: Session, plaintext_key: str) -> PlatformPrincipal:
        """校验平台 API Key，并返回可信的平台请求身份。"""
        cleaned_key = plaintext_key.strip()
        if not cleaned_key:
            raise BusinessException(code=401, msg="缺少平台 API Key")

        api_key_record = self.repository.get_api_key_by_hash(db, hash_platform_api_key(cleaned_key))
        if api_key_record is None or api_key_record.status != "enabled":
            raise BusinessException(code=401, msg="平台 API Key 无效或已停用")

        if api_key_record.expires_at is not None:
            expires_at = api_key_record.expires_at
            current_time = datetime.now(tz=expires_at.tzinfo) if expires_at.tzinfo else datetime.now()
            if expires_at <= current_time:
                raise BusinessException(code=401, msg="平台 API Key 已过期")

        platform = self.repository.get_platform_by_id(db, api_key_record.platform_id)
        if platform is None or platform.id is None or platform.status != "enabled":
            raise BusinessException(code=403, msg="业务平台不存在或已停用")
        if api_key_record.id is None:
            raise RuntimeError("平台 API Key 记录缺少数据库主键")

        return PlatformPrincipal(
            platform_id=platform.id,
            platform_code=platform.platform_code,
            platform_name=platform.platform_name,
            api_key_id=api_key_record.id,
        )

    def validate_platform_ids(self, db: Session, platform_ids: list[int]) -> list[int]:
        """清理并校验资源绑定请求中的业务平台 ID。"""
        normalized_ids = list(dict.fromkeys(platform_ids))
        if not normalized_ids:
            raise BusinessException(code=422, msg="至少绑定一个业务平台")
        existing_ids = self.repository.list_existing_platform_ids(db, normalized_ids)
        missing_ids = [platform_id for platform_id in normalized_ids if platform_id not in existing_ids]
        if missing_ids:
            raise BusinessException(code=422, msg=f"业务平台不存在: {missing_ids}")
        return normalized_ids

    def replace_agent_platforms(
        self,
        db: Session,
        *,
        agent_template_id: int,
        platform_ids: list[int],
    ) -> None:
        """校验后完整替换 Agent 模板的平台绑定。"""
        normalized_ids = self.validate_platform_ids(db, platform_ids)
        self.repository.replace_agent_platforms(
            db,
            agent_template_id=agent_template_id,
            platform_ids=normalized_ids,
        )

    def replace_tool_platforms(
        self,
        db: Session,
        *,
        mcp_tool_id: int,
        platform_ids: list[int],
    ) -> None:
        """校验后完整替换 MCP Tool 的平台绑定。"""
        normalized_ids = self.validate_platform_ids(db, platform_ids)
        self.repository.replace_tool_platforms(
            db,
            mcp_tool_id=mcp_tool_id,
            platform_ids=normalized_ids,
        )

    def validate_tool_platform_change(
        self,
        db: Session,
        *,
        tool_name: str,
        platform_ids: list[int],
    ) -> None:
        """阻止 MCP Tool 平台变更破坏已经保存的 Agent 工具配置。"""
        target_platform_ids = set(platform_ids)
        invalid_agent_ids: list[str] = []
        templates = self.repository.list_agent_templates_using_tool(db, tool_name)
        for template in templates:
            if template.id is None:
                continue
            agent_platform_ids = set(self.repository.get_platform_ids_for_agent(db, template.id))
            if not agent_platform_ids.issubset(target_platform_ids):
                invalid_agent_ids.append(template.agent_id)
        if invalid_agent_ids:
            raise BusinessException(
                code=409,
                msg="调整工具平台绑定会导致以下 Agent 配置失效: " + ", ".join(invalid_agent_ids),
            )

    def validate_tools_can_be_deleted(self, db: Session, tool_names: list[str]) -> None:
        """阻止删除仍被 Agent 模板引用的 MCP Tool。"""
        self._validate_tools_not_in_use(db, tool_names, operation_name="删除")

    def validate_tools_can_be_disabled(self, db: Session, tool_names: list[str]) -> None:
        """阻止停用仍被 Agent 模板引用的 MCP Tool。"""
        self._validate_tools_not_in_use(db, tool_names, operation_name="停用")

    def _validate_tools_not_in_use(
        self,
        db: Session,
        tool_names: list[str],
        *,
        operation_name: str,
    ) -> None:
        """统一校验工具不存在 Agent 引用，并在错误中列出受影响 Agent。"""
        tool_usage: list[str] = []
        for tool_name in tool_names:
            templates = self.repository.list_agent_templates_using_tool(db, tool_name)
            if not templates:
                continue

            # 明确列出受影响 Agent，方便管理员先解除模板工具配置，
            # 避免删除后在 Agent 组装阶段才遇到“工具不存在”的运行时错误。
            agent_ids = [template.agent_id for template in templates]
            tool_usage.append(f"{tool_name}（Agent: {', '.join(agent_ids)}）")

        if tool_usage:
            raise BusinessException(
                code=409,
                msg=(
                    f"以下 MCP Tool 仍被 Agent 使用，不能{operation_name}: "
                    + "; ".join(tool_usage)
                    + "。请先在对应 Agent 配置中移除这些工具后再操作。"
                ),
            )

    def validate_agent_tool_platforms(
        self,
        db: Session,
        *,
        platform_ids: list[int],
        tool_names: list[str],
    ) -> None:
        """校验每个 MCP Tool 的平台集合能够完整覆盖 Agent 平台集合。"""
        if not tool_names:
            return
        required_platform_ids = set(platform_ids)
        tool_platform_ids = self.repository.get_tool_platform_ids_by_names(db, tool_names)
        invalid_tool_names = [
            tool_name
            for tool_name in tool_names
            if not required_platform_ids.issubset(tool_platform_ids.get(tool_name, set()))
        ]
        if invalid_tool_names:
            raise BusinessException(
                code=422,
                msg="以下 MCP Tool 未覆盖 Agent 绑定的全部业务平台: " + ", ".join(invalid_tool_names),
            )

    def require_agent_binding(self, db: Session, *, agent_id: str, platform_id: int) -> None:
        """要求当前业务平台已经绑定目标 Agent。"""
        if not self.repository.is_agent_bound_to_platform(db, agent_id=agent_id, platform_id=platform_id):
            raise BusinessException(code=403, msg=f"当前业务平台未绑定 Agent: {agent_id}")

    @staticmethod
    def to_platform_view(platform: BusinessPlatform) -> BusinessPlatformView:
        """把业务平台 ORM 模型转换为脱离 Session 的接口视图。"""
        if platform.id is None:
            raise RuntimeError("业务平台记录缺少数据库主键")
        return BusinessPlatformView(
            id=platform.id,
            platform_code=platform.platform_code,
            platform_name=platform.platform_name,
            description=platform.description,
            status=platform.status,
            created_at=platform.created_at.isoformat() if platform.created_at else None,
            updated_at=platform.updated_at.isoformat() if platform.updated_at else None,
        )

    @staticmethod
    def to_api_key_view(api_key: BusinessPlatformAPIKey) -> BusinessPlatformAPIKeyView:
        """把 API Key ORM 记录转换为内网管理端完整视图。"""
        if api_key.id is None:
            raise RuntimeError("平台 API Key 记录缺少数据库主键")
        return BusinessPlatformAPIKeyView(
            id=api_key.id,
            platform_id=api_key.platform_id,
            key_name=api_key.key_name,
            key_prefix=api_key.key_prefix,
            api_key=api_key.api_key,
            status=api_key.status,
            expires_at=api_key.expires_at.isoformat() if api_key.expires_at else None,
            created_at=api_key.created_at.isoformat() if api_key.created_at else None,
            updated_at=api_key.updated_at.isoformat() if api_key.updated_at else None,
        )
