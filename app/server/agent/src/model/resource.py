"""从平台模型配置表解析可调用的模型资源。"""

from dataclasses import dataclass
from typing import Any

from app.common.db.postgres_db import get_db_session
from app.server.agent.src.model.service import ModelConfigService


@dataclass(frozen=True, slots=True)
class ModelRuntimeResource:
    """模型调用所需的稳定连接信息。"""

    model_code: str
    model_name: str
    model_type: str
    base_url: str
    api_key: str | None
    extra_config: dict[str, Any]

    @property
    def dimension(self) -> int | None:
        """读取 Embedding 模型配置中的向量维度。"""
        value = self.extra_config.get("dimension")
        return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None

    @property
    def embedding_batch_size(self) -> int:
        """读取 Embedding 批大小，未配置时使用兼容性较好的默认值 32。"""
        value = self.extra_config.get("batch_size", 32)
        if isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= 256:
            return value
        raise ValueError(
            f"Embedding 模型 {self.model_code} 的 extra_config.batch_size 必须是 1 到 256 的整数"
        )


def resolve_model_resource(model_code: str, model_type: str) -> ModelRuntimeResource:
    """按 model_code 从 model_configs 解析指定类型的已启用模型。"""
    service = ModelConfigService()
    with get_db_session() as db:
        record = service.require_enabled_model(db, model_code, model_type)
        return ModelRuntimeResource(
            model_code=record.model_code,
            model_name=record.model_name,
            model_type=record.model_type,
            base_url=record.base_url.rstrip("/"),
            api_key=record.api_key,
            extra_config=dict(record.extra_config or {}),
        )
