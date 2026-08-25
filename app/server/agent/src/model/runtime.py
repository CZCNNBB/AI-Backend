import logging
import os
from typing import Any

from sqlmodel import Session

from app.common.db.postgres_db import get_db_session
from app.server.agent.src.model.constants import (
    DEFAULT_MODEL_MAX_RETRIES,
    DEFAULT_MODEL_TIMEOUT_SECONDS,
)
from app.server.agent.src.model.openai_chat import ReasoningChatOpenAI
from app.server.agent.src.model.service import ModelConfigService


logger = logging.getLogger("ai_backend.agent.model")


class AgentModelService:
    """Agent 服务的模型调用入口。"""

    def __init__(self, model_config_service: ModelConfigService | None = None):
        """初始化 Agent 模型服务。"""
        self.model_config_service = model_config_service or ModelConfigService()

    def configure_langsmith_environment(self) -> None:
        """根据环境变量配置 LangSmith 追踪开关。"""
        tracing_enabled = (os.getenv("LANGSMITH_TRACING") or "false").strip().lower() in {
            "1",
            "true",
            "yes",
            "y",
            "on",
        }
        os.environ["LANGSMITH_TRACING"] = "true" if tracing_enabled else "false"
        os.environ["LANGCHAIN_TRACING_V2"] = "true" if tracing_enabled else "false"
        if not tracing_enabled:
            return

        endpoint = os.getenv("LANGSMITH_ENDPOINT", "https://api.smith.langchain.com").strip()
        project = os.getenv("LANGSMITH_PROJECT", "career-ai").strip()
        api_key = os.getenv("LANGSMITH_API_KEY", "").strip()
        os.environ["LANGSMITH_ENDPOINT"] = endpoint
        os.environ["LANGCHAIN_ENDPOINT"] = endpoint
        os.environ["LANGSMITH_PROJECT"] = project
        os.environ["LANGCHAIN_PROJECT"] = project
        if api_key:
            os.environ["LANGSMITH_API_KEY"] = api_key
            os.environ["LANGCHAIN_API_KEY"] = api_key

    def create_chat_model(
        self,
        *,
        db: Session | None = None,
        model_code: str | None = None,
        temperature: float = 0.2,
        timeout_seconds: int = DEFAULT_MODEL_TIMEOUT_SECONDS,
        max_retries: int = DEFAULT_MODEL_MAX_RETRIES,
    ) -> Any:
        """根据 model_code 从数据库读取配置并创建 LangChain ChatModel。"""
        self.configure_langsmith_environment()

        # API 主流程会传入同一个请求 Session；A2A 子 Agent 可能传 db=None，
        # 此时模型服务自己短暂打开一个 Session，只用于读取模型配置，不写业务会话。
        if db is not None:
            definition = self.model_config_service.require_enabled_chat_model(db, model_code)
        else:
            with get_db_session() as inner_db:
                definition = self.model_config_service.require_enabled_chat_model(inner_db, model_code)

        effective_timeout = timeout_seconds
        logger.info(
            "聊天模型初始化中: model_code=%s model_name=%s base_url=%s temperature=%s timeout=%s max_retries=%s",
            definition.model_code,
            definition.model_name,
            definition.base_url,
            temperature,
            effective_timeout,
            max_retries,
        )

        extra_config = dict(definition.extra_config or {})
        model_kwargs = dict(extra_config.pop("model_kwargs", {}) or {})
        # OpenAI 兼容接口默认允许模型一次返回多个工具调用。
        # 我们的 Agent 需要按顺序执行工具，尤其是 A2A 子 Agent 调用必须等待结果返回后，
        # 主 Agent 才能继续更新任务计划或进入下一步，因此这里默认关闭并行工具调用。
        model_kwargs.setdefault("parallel_tool_calls", False)
        logger.info(
            "聊天模型额外配置: model_code=%s extra_keys=%s model_kwargs_keys=%s",
            definition.model_code,
            sorted(extra_config.keys()),
            sorted(model_kwargs.keys()),
        )

        chat_model = ReasoningChatOpenAI(
            api_key=definition.api_key,
            base_url=definition.base_url or None,
            model=definition.model_name,
            temperature=temperature,
            timeout=effective_timeout,
            max_retries=max_retries,
            model_kwargs=model_kwargs,
            **extra_config,
        )
        logger.info("聊天模型初始化完成: model_code=%s model_name=%s", definition.model_code, definition.model_name)
        return chat_model

    def create_embedding_model(self, *, db: Session | None = None, model_code: str | None = None) -> Any:
        """创建 Embedding 模型的预留入口，当前知识库流程尚未接入。"""
        raise NotImplementedError("Embedding 模型接入将在知识库模块实现时补充")


def create_chat_model(
    *,
    db: Session | None = None,
    model_code: str | None = None,
    temperature: float = 0.2,
    timeout_seconds: int = DEFAULT_MODEL_TIMEOUT_SECONDS,
    max_retries: int = DEFAULT_MODEL_MAX_RETRIES,
) -> Any:
    """创建 Agent 聊天模型的便捷函数。"""
    return AgentModelService().create_chat_model(
        db=db,
        model_code=model_code,
        temperature=temperature,
        timeout_seconds=timeout_seconds,
        max_retries=max_retries,
    )
