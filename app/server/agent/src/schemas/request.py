from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.server.agent.src.model.constants import (
    DEFAULT_MODEL_MAX_RETRIES,
    DEFAULT_MODEL_TIMEOUT_SECONDS,
)
from app.server.agent.src.schemas.context_summarization import ContextSummarizationConfig


class ModelRuntimeOptions(BaseModel):
    """单次模型调用的运行参数。

    这里只描述“怎么调用模型”。模型连接信息通过 model_code 从 model 表模块中的 model_configs 表读取；
    temperature、timeout_seconds、max_retries 属于具体 Agent/任务场景，因此保留在运行参数里。
    """

    model_code: str | None = Field(
        default=None,
        description="平台模型编码，必须指向 model_configs 中已启用的 chat 模型。",
    )
    temperature: float = Field(
        default=0.2,
        ge=0,
        le=2,
        description="模型采样温度，数值越低输出越稳定，数值越高输出越发散。",
    )
    timeout_seconds: int = Field(
        default=DEFAULT_MODEL_TIMEOUT_SECONDS,
        ge=1,
        description="模型调用超时时间；Chat、Embedding、Rerank 共用同一默认值。",
    )
    max_retries: int = Field(
        default=DEFAULT_MODEL_MAX_RETRIES,
        ge=0,
        description="模型调用失败时的最大重试次数。",
    )

    @field_validator("model_code")
    @classmethod
    def normalize_model_code(cls, value: str | None) -> str | None:
        """清理模型编码两侧空白，空字符串视为未配置。"""
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class AgentOptionalFeatures(BaseModel):
    """本次 Agent 运行可以显式开启的增强能力。

    基础能力，例如工具调用日志、工具错误处理、检索上下文注入，已经由中间件默认装配，
    不再通过请求参数控制。
    """

    long_term_memory_enabled: bool = Field(
        default=False,
        description="是否启用长期记忆能力；当前为预留能力，不等同于 conversation_id 控制的会话上下文。",
    )
    planning_enabled: bool = Field(
        default=False,
        description="是否启用规划模式；开启后自动装配任务计划工具和规划中间件。",
    )
    knowledge_enabled: bool = Field(
        default=False,
        description="模板是否具备知识库检索能力；具体知识库白名单由每次调用的 knowledge 参数提供。",
    )


class AgentKnowledgeConfig(BaseModel):
    """Agent 单次运行可访问的知识库范围。"""

    knowledge_base_ids: list[str] = Field(
        default_factory=list,
        max_length=20,
        description="本次运行允许检索的知识库 ID 白名单；模型不能修改该范围。",
    )

    @field_validator("knowledge_base_ids")
    @classmethod
    def normalize_knowledge_base_ids(cls, values: list[str]) -> list[str]:
        """清理知识库 ID，并按原顺序去重。"""
        cleaned = [str(value or "").strip() for value in values if str(value or "").strip()]
        return list(dict.fromkeys(cleaned))


class AgentA2AConfig(BaseModel):
    """A2A 调用配置。

    只要 sub_agent_list 非空，本次 Agent 运行就会动态装配 a2a_call 工具，
    并通过 A2A 中间件把可调用子 Agent 信息注入系统提示词。
    """

    sub_agent_list: list[str] = Field(
        default_factory=list,
        description="本次允许调用的子 Agent ID 列表；为空或不传时不启用 A2A。",
    )


class AgentRuntimeCredentials(BaseModel):
    """仅在本次 Agent 执行期间使用的敏感业务凭证。"""

    business_token: str | None = Field(
        default=None,
        exclude=True,
        repr=False,
        description="来自 X-Business-Authorization、仅供 MCP Tool 原样透传的业务用户凭证",
    )


class AgentRunRequest(BaseModel):
    """通用 Agent 底层运行请求模型。

    该模型主要供 AgentMessageService 和编排层内部调用：
    - 传 agent_id：以 Agent 模板配置为主运行，请求体只提供 query、conversation_id、stream 等本次调用参数。
    - 不传 agent_id：按请求体中的临时配置直接运行。

    conversation_id 是会话记忆的唯一开关：
    - conversation_id 非空：作为 LangGraph thread_id，启用 PostgreSQL checkpointer，并写入用户可见会话记录。
    - conversation_id 为空：视为一次性任务或 A2A 子 Agent 调用，不启用 checkpointer，不写入 agent_conversations / agent_messages。
    """

    agent_id: str | None = Field(
        default=None,
        max_length=100,
        description="可选 Agent 模板 ID；传入后后端会自动加载模板配置，并以模板中的核心配置为主。",
    )
    platform_id: int | None = Field(default=None, description="可信平台身份，由 API Key 认证依赖注入")
    external_user_id: str | None = Field(default=None, max_length=150, description="外部业务平台用户标识")
    runtime_credentials: AgentRuntimeCredentials = Field(
        default_factory=AgentRuntimeCredentials,
        exclude=True,
        repr=False,
        description="本次执行使用的敏感运行时凭证，不进入持久化配置",
    )
    query: str = Field(..., min_length=1, description="用户输入或编排层传入的任务指令。")
    conversation_id: str | None = Field(
        default=None,
        description="会话 ID；非空时启用 checkpointer 和会话记录，空值时按一次性无会话任务运行。",
    )
    stream: bool = Field(default=False, description="是否使用 SSE 流式返回。")
    system_prompt: str | None = Field(default=None, description="本次运行使用的系统提示词。")
    inputs: dict[str, Any] = Field(default_factory=dict, description="编排层注入的业务变量。")
    file_ids: list[str] = Field(default_factory=list, description="附件文件 ID 列表。")
    tools: list[str] = Field(
        default_factory=list,
        description="本次运行允许加载的常规工具名称；A2A 工具由 a2a.sub_agent_list 动态控制。",
    )
    optional_features: AgentOptionalFeatures = Field(
        default_factory=AgentOptionalFeatures,
        description="本次运行可选增强能力。",
    )
    knowledge: AgentKnowledgeConfig | None = Field(
        default=None,
        description="本次运行允许访问的知识库范围；仅在模板开启知识库能力时生效。",
    )
    a2a: AgentA2AConfig | None = Field(default=None, description="A2A 调用配置。")
    context_summarization: ContextSummarizationConfig | None = Field(
        default=None,
        description="仅由 Agent 模板解析后写入的会话总结配置；普通调用方不应传入。",
    )
    runtime_options: ModelRuntimeOptions = Field(
        default_factory=ModelRuntimeOptions,
        description="模型运行参数，必须包含可用 chat 模型的 model_code。",
    )

    @field_validator("agent_id", "external_user_id")
    @classmethod
    def normalize_agent_id(cls, value: str | None) -> str | None:
        """清理 Agent 模板 ID 两侧空白，空字符串视为未传。"""
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class AgentMessageRequest(BaseModel):
    """统一 Agent 消息入口请求模型。

    该模型用于正式对外的 /agent/messages 接口。
    前端不需要关心本次输入是新任务还是中断恢复；后端会根据 conversation_id
    自动判断是否存在 interrupted 状态的运行，并路由到 run 或 resume。
    """

    agent_id: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="必须提供的 Agent 模板 ID；中断恢复时仍会校验原运行归属。",
    )
    external_user_id: str = Field(
        ...,
        min_length=1,
        max_length=150,
        description="业务平台中的稳定用户 ID，用于隔离会话、消息和运行记录",
    )
    conversation_id: str | None = Field(
        default=None,
        description="会话 ID；用于查找当前会话是否存在等待恢复的中断运行。",
    )
    message: str = Field(
        default="",
        description="用户本次输入文本；表单提交或按钮确认时可以是前端生成的摘要文本。",
    )
    message_type: str = Field(
        default="text",
        description="消息类型，例如 text/form_submit/action_click/file_submit。",
    )
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description="结构化消息负载；中断恢复时建议使用 {type: string, data: object}。",
    )
    stream: bool = Field(default=True, description="是否使用 SSE 流式返回。")
    system_prompt: str | None = Field(default=None, description="新任务运行时使用的临时系统提示词。")
    inputs: dict[str, Any] = Field(default_factory=dict, description="新任务运行时注入的业务变量。")
    file_ids: list[str] = Field(default_factory=list, description="附件文件 ID 列表。")
    tools: list[str] = Field(default_factory=list, description="新任务运行时允许加载的常规工具名称。")
    optional_features: AgentOptionalFeatures = Field(
        default_factory=AgentOptionalFeatures,
        description="新任务运行时可选增强能力。",
    )
    knowledge: AgentKnowledgeConfig | None = Field(
        default=None,
        description="新任务运行时允许访问的知识库范围。",
    )
    a2a: AgentA2AConfig | None = Field(default=None, description="新任务运行时的 A2A 调用配置。")
    runtime_options: ModelRuntimeOptions = Field(
        default_factory=ModelRuntimeOptions,
        description="新任务运行时的模型参数。",
    )

    @field_validator("conversation_id")
    @classmethod
    def normalize_optional_id(cls, value: str | None) -> str | None:
        """清理可选 ID 两侧空白，空字符串视为未传。"""
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @field_validator("agent_id", "external_user_id")
    @classmethod
    def normalize_required_identity(cls, value: str) -> str:
        """清理必填 Agent 和用户标识，并拒绝只包含空白字符的输入。"""
        stripped = value.strip()
        if not stripped:
            raise ValueError("必填身份标识不能为空")
        return stripped

    @field_validator("message_type")
    @classmethod
    def normalize_message_type(cls, value: str) -> str:
        """清理消息类型，缺省时使用 text。"""
        stripped = (value or "").strip()
        return stripped or "text"

    @field_validator("message")
    @classmethod
    def normalize_message(cls, value: str) -> str:
        """清理消息文本；结构化表单提交允许文本为空。"""
        return (value or "").strip()


class AgentResumeRequest(BaseModel):
    """Agent 底层中断恢复请求模型。

    该模型主要供 AgentMessageService 内部使用，用于恢复已经触发 LangGraph interrupt 的 Agent 运行。
    恢复时必须带回中断事件中的 run_id 和 thread_id，并传入固定格式的 resume_value。
    """

    run_id: str = Field(..., min_length=1, description="被中断的 Agent 运行 ID。")
    conversation_id: str = Field(..., min_length=1, description="用户可见的业务会话 ID。")
    thread_id: str = Field(..., min_length=1, description="AI-backend 内部生成的 LangGraph checkpoint 线程 ID。")
    platform_id: int = Field(..., description="可信业务平台 ID。")
    external_user_id: str = Field(..., min_length=1, max_length=150, description="外部业务平台用户 ID。")
    runtime_credentials: AgentRuntimeCredentials = Field(
        default_factory=AgentRuntimeCredentials,
        exclude=True,
        repr=False,
        description="恢复执行本次请求携带的敏感业务凭证。",
    )
    resume_value: dict[str, Any] = Field(
        ...,
        description="恢复值，固定外层格式为 {type: string, data: object}。",
    )
    stream: bool = Field(default=True, description="是否使用 SSE 流式返回恢复后的事件。")

    @field_validator("run_id", "thread_id", "conversation_id", "external_user_id")
    @classmethod
    def normalize_required_id(cls, value: str) -> str:
        """清理必填 ID 两侧空白。"""
        return value.strip()

    @field_validator("resume_value")
    @classmethod
    def validate_resume_value(cls, value: dict[str, Any]) -> dict[str, Any]:
        """校验 resume_value 的最小协议格式。"""
        if not isinstance(value, dict):
            raise ValueError("resume_value 必须是对象")
        resume_type = str(value.get("type") or "").strip()
        if not resume_type:
            raise ValueError("resume_value.type 不能为空")
        data = value.get("data")
        if data is None:
            data = {}
        if not isinstance(data, dict):
            raise ValueError("resume_value.data 必须是对象")
        return {"type": resume_type, "data": data}
