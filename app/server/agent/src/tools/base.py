from typing import Any

from pydantic import BaseModel, Field


class AgentToolDefinition(BaseModel):
    """Agent 工具定义。"""

    name: str = Field(..., description="工具名称")
    description: str = Field(default="", description="工具说明")
    callable_ref: Any | None = Field(default=None, description="LangChain Tool、工具函数或其他可执行工具对象")

    class Config:
        """Pydantic 模型配置。"""

        arbitrary_types_allowed = True
