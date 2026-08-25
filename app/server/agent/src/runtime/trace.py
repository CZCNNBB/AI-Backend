from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class AgentTraceEvent(BaseModel):
    """Agent 运行过程中的追踪事件。"""

    event_type: str = Field(..., description="事件类型")
    message: str = Field(default="", description="事件说明")
    payload: dict[str, Any] = Field(default_factory=dict, description="事件数据")
    created_at: datetime = Field(default_factory=datetime.now, description="事件创建时间")
