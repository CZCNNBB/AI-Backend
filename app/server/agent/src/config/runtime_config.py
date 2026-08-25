import os
from dataclasses import dataclass
from functools import lru_cache

from dotenv import load_dotenv


# Agent 服务可能由 FastAPI、测试或独立脚本加载，因此在配置层统一读取项目环境变量。
load_dotenv(override=True)


def _read_positive_int(name: str, default: int) -> int:
    """读取正整数环境变量，缺失或非法时使用默认值。

    Args:
        name: 环境变量名称。
        default: 默认正整数。

    Returns:
        解析后的正整数。
    """
    raw_value = (os.getenv(name) or "").strip()
    try:
        parsed_value = int(raw_value)
    except ValueError:
        return default
    return parsed_value if parsed_value > 0 else default


@dataclass(frozen=True)
class AgentRuntimeSettings:
    """Agent 平台级运行阈值配置。"""

    context_summary_trigger_tokens: int
    context_summary_keep_messages: int
    context_summary_trim_tokens: int
    recursion_limit: int
    tool_error_max_length: int

    @classmethod
    def from_env(cls) -> "AgentRuntimeSettings":
        """从环境变量构建 Agent 平台级运行配置。

        Returns:
            完成基础校验的 AgentRuntimeSettings。
        """
        return cls(
            context_summary_trigger_tokens=_read_positive_int(
                "AGENT_CONTEXT_SUMMARY_TRIGGER_TOKENS", 12_000
            ),
            context_summary_keep_messages=_read_positive_int(
                "AGENT_CONTEXT_SUMMARY_KEEP_MESSAGES", 20
            ),
            context_summary_trim_tokens=_read_positive_int(
                "AGENT_CONTEXT_SUMMARY_TRIM_TOKENS", 4_000
            ),
            recursion_limit=_read_positive_int("AGENT_RECURSION_LIMIT", 50),
            tool_error_max_length=_read_positive_int("AGENT_TOOL_ERROR_MAX_LENGTH", 500),
        )


@lru_cache(maxsize=1)
def get_agent_runtime_settings() -> AgentRuntimeSettings:
    """获取当前进程缓存的 Agent 平台级运行配置。

    Returns:
        AgentRuntimeSettings 单例。
    """
    return AgentRuntimeSettings.from_env()
