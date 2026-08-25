import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field, SecretStr, ValidationError


# Agent 服务仍加载 .env 中的服务、数据库和 LangSmith 配置；模型连接配置改由 YAML 管理。
load_dotenv(override=True)


def env_bool(name: str, default: bool = False) -> bool:
    """
    读取布尔类型环境变量。

    Args:
        name: 环境变量名称。
        default: 环境变量缺失时使用的默认值。

    Returns:
        解析后的布尔值。
    """
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


class GatewayModelDefinition(BaseModel):
    """model_gateway.yaml 中单个模型别名的连接配置。"""

    kind: Literal["llm", "embedding", "reranker"] = Field(description="模型能力类型")
    provider: str = Field(description="模型供应商或调用协议")
    base_url: str = Field(description="模型服务地址")
    model: str = Field(description="供应商侧真实模型名称")
    api_key: SecretStr = Field(description="模型 API Key")
    timeout: int = Field(default=60, ge=1, description="模型调用默认超时时间")
    dimension: int | None = Field(default=None, ge=1, description="Embedding 向量维度")

    def get_api_key(self) -> str:
        """
        获取当前模型定义中的明文 API Key。

        Returns:
            可传给模型客户端的 API Key。
        """
        return self.api_key.get_secret_value()


class ModelGatewayDefaults(BaseModel):
    """模型网关默认模型别名配置。"""

    chat: str = Field(default="chat_main", description="默认聊天模型别名")
    embedding: str | None = Field(default="embed_search", description="默认 Embedding 模型别名")
    rerank: str | None = Field(default="rerank_default", description="默认 Rerank 模型别名")


class ModelGatewayFile(BaseModel):
    """model_gateway.yaml 顶层配置结构。"""

    defaults: ModelGatewayDefaults = Field(default_factory=ModelGatewayDefaults, description="默认模型别名")
    models: dict[str, GatewayModelDefinition] = Field(default_factory=dict, description="模型别名映射")


class ModelConfig(BaseModel):
    """Agent 服务使用的模型网关和 LangSmith 配置。"""

    gateway_path: str = Field(description="model_gateway.yaml 的绝对路径")
    models: dict[str, GatewayModelDefinition] = Field(default_factory=dict, description="模型别名映射")
    default_chat_alias: str = Field(default="chat_main", description="默认聊天模型别名")
    default_embedding_alias: str | None = Field(default="embed_search", description="默认 Embedding 模型别名")
    default_rerank_alias: str | None = Field(default="rerank_default", description="默认 Rerank 模型别名")
    langsmith_tracing: bool = Field(default=False, description="是否启用 LangSmith 追踪")
    langsmith_api_key: SecretStr | None = Field(default=None, description="LangSmith API Key")
    langsmith_endpoint: str = Field(default="https://api.smith.langchain.com", description="LangSmith 地址")
    langsmith_project: str = Field(default="career-ai", description="LangSmith 项目名")

    @property
    def provider(self) -> str:
        """返回默认聊天模型供应商。"""
        return self.resolve_model(self.default_chat_alias, expected_kind="llm").provider

    @property
    def base_url(self) -> str:
        """返回默认聊天模型服务地址。"""
        return self.resolve_model(self.default_chat_alias, expected_kind="llm").base_url

    @property
    def chat_model(self) -> str:
        """返回默认聊天模型别名。"""
        return self.default_chat_alias

    @property
    def embedding_model(self) -> str | None:
        """返回默认 Embedding 模型别名。"""
        return self.default_embedding_alias

    @property
    def rerank_model(self) -> str | None:
        """返回默认 Rerank 模型别名。"""
        return self.default_rerank_alias

    def get_api_key(self) -> str:
        """
        获取默认聊天模型的明文 API Key。

        Returns:
            默认聊天模型 API Key。
        """
        return self.resolve_model(self.default_chat_alias, expected_kind="llm").get_api_key()

    def get_langsmith_api_key(self) -> str:
        """
        获取明文 LangSmith API Key。

        Returns:
            可写入 LangSmith 环境变量的 API Key。
        """
        return self.langsmith_api_key.get_secret_value() if self.langsmith_api_key else ""

    def resolve_model(
        self,
        alias: str | None,
        *,
        expected_kind: Literal["llm", "embedding", "reranker"],
    ) -> GatewayModelDefinition:
        """
        根据模型别名解析并校验模型定义。

        Args:
            alias: model_gateway.yaml 中的模型别名；为空时按能力类型选择默认别名。
            expected_kind: 调用方期望的模型能力类型。

        Returns:
            与别名和能力类型匹配的模型定义。

        Raises:
            RuntimeError: 别名不存在、模型类型不匹配或配置不完整。
        """
        selected_alias = alias or self._default_alias_for_kind(expected_kind)
        if not selected_alias:
            raise RuntimeError(f"未配置 {expected_kind} 类型的默认模型别名")

        definition = self.models.get(selected_alias)
        if definition is None:
            raise RuntimeError(f"model_gateway.yaml 中不存在模型别名: {selected_alias}")
        if definition.kind != expected_kind:
            raise RuntimeError(
                f"模型别名 {selected_alias} 的类型为 {definition.kind}，不能用于 {expected_kind}"
            )
        if definition.provider != "openai_compatible" and expected_kind in {"llm", "embedding"}:
            raise RuntimeError(f"暂不支持的模型供应商: {definition.provider}")
        if not definition.get_api_key():
            raise RuntimeError(f"模型别名 {selected_alias} 未配置 api_key")
        return definition

    def _default_alias_for_kind(
        self,
        kind: Literal["llm", "embedding", "reranker"],
    ) -> str | None:
        """
        返回指定能力类型的默认模型别名。

        Args:
            kind: 模型能力类型。

        Returns:
            对应的默认模型别名。
        """
        if kind == "llm":
            return self.default_chat_alias
        if kind == "embedding":
            return self.default_embedding_alias
        return self.default_rerank_alias

    def validate_for_runtime(self) -> None:
        """
        校验默认聊天模型是否可以正常用于 Agent。

        Raises:
            RuntimeError: 默认聊天模型配置不可用。
        """
        self.resolve_model(self.default_chat_alias, expected_kind="llm")


def find_model_gateway_path() -> Path:
    """
    返回 Agent 根目录中的 model_gateway.yaml 路径。

    Returns:
        Agent 模型网关配置文件的绝对路径。

    Raises:
        RuntimeError: Agent 根目录中不存在模型网关配置文件。
    """
    # config.py 位于 agent/src/model，向上两级即 agent 模块根目录。
    gateway_path = Path(__file__).resolve().parents[2] / "model_gateway.yaml"
    if not gateway_path.is_file():
        raise RuntimeError(
            "未找到 model_gateway.yaml，请将其放在 "
            "AI-backend/app/server/agent 根目录"
        )
    return gateway_path


def load_model_gateway_file(path: Path) -> ModelGatewayFile:
    """
    读取并校验模型网关 YAML 文件。

    Args:
        path: model_gateway.yaml 文件路径。

    Returns:
        通过 Pydantic 校验的模型网关配置。

    Raises:
        RuntimeError: YAML 读取失败、格式错误或没有模型定义。
    """
    try:
        raw_config = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as error:
        raise RuntimeError(f"读取 model_gateway.yaml 失败: {error}") from error

    try:
        gateway = ModelGatewayFile.model_validate(raw_config)
    except ValidationError as error:
        raise RuntimeError(f"model_gateway.yaml 配置格式错误: {error}") from error
    if not gateway.models:
        raise RuntimeError("model_gateway.yaml 未配置任何模型")
    return gateway


@lru_cache(maxsize=1)
def get_model_config() -> ModelConfig:
    """
    从 Agent 根目录 model_gateway.yaml 读取并缓存模型配置。

    Returns:
        当前进程复用的模型网关配置。
    """
    gateway_path = find_model_gateway_path()
    gateway = load_model_gateway_file(gateway_path)
    config = ModelConfig(
        gateway_path=str(gateway_path),
        models=gateway.models,
        default_chat_alias=gateway.defaults.chat,
        default_embedding_alias=gateway.defaults.embedding,
        default_rerank_alias=gateway.defaults.rerank,
        langsmith_tracing=env_bool("LANGSMITH_TRACING", False),
        langsmith_api_key=os.getenv("LANGSMITH_API_KEY") or None,
        langsmith_endpoint=os.getenv("LANGSMITH_ENDPOINT", "https://api.smith.langchain.com").strip(),
        langsmith_project=os.getenv("LANGSMITH_PROJECT", "career-ai").strip(),
    )
    config.validate_for_runtime()
    return config


def configure_langsmith_environment(config: ModelConfig | None = None) -> None:
    """
    根据配置写入 LangSmith 追踪所需的环境变量。

    Args:
        config: 外部传入的模型配置；不传时读取当前缓存配置。
    """
    current_config = config or get_model_config()
    if not current_config.langsmith_tracing:
        os.environ["LANGSMITH_TRACING"] = "false"
        os.environ["LANGCHAIN_TRACING_V2"] = "false"
        return

    os.environ["LANGSMITH_TRACING"] = "true"
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGSMITH_ENDPOINT"] = current_config.langsmith_endpoint
    os.environ["LANGCHAIN_ENDPOINT"] = current_config.langsmith_endpoint
    os.environ["LANGSMITH_PROJECT"] = current_config.langsmith_project
    os.environ["LANGCHAIN_PROJECT"] = current_config.langsmith_project

    langsmith_api_key = current_config.get_langsmith_api_key()
    if langsmith_api_key:
        os.environ["LANGSMITH_API_KEY"] = langsmith_api_key
        os.environ["LANGCHAIN_API_KEY"] = langsmith_api_key
