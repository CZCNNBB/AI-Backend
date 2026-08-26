import os
from dataclasses import dataclass

from dotenv import load_dotenv


# MinerU 客户端可能由文件接口、知识库后台任务或独立脚本创建，统一加载项目环境变量。
load_dotenv(override=True)


def _read_positive_float(name: str, default: float) -> float:
    """读取正浮点数环境变量，缺失或非法时回退默认值。

    Args:
        name: 环境变量名称。
        default: 缺失、格式错误或非正数时使用的默认值。

    Returns:
        大于 0 的浮点数配置值。
    """
    raw_value = (os.getenv(name) or "").strip()
    try:
        parsed_value = float(raw_value)
    except ValueError:
        return default
    return parsed_value if parsed_value > 0 else default


def _read_bool(name: str, default: bool) -> bool:
    """读取布尔环境变量，并兼容常见的开关写法。

    Args:
        name: 环境变量名称。
        default: 环境变量缺失或无法识别时使用的默认值。

    Returns:
        解析后的布尔值。
    """
    raw_value = (os.getenv(name) or "").strip().lower()
    if not raw_value:
        return default
    if raw_value in {"1", "true", "yes", "on", "enabled"}:
        return True
    if raw_value in {"0", "false", "no", "off", "disabled"}:
        return False
    return default


@dataclass(frozen=True)
class MinerUConfig:
    """本地 MinerU 异步解析服务配置。"""

    enabled: bool
    base_url: str
    health_timeout_seconds: float
    request_timeout_seconds: float
    task_timeout_seconds: float
    poll_interval_seconds: float

    @classmethod
    def from_env(cls) -> "MinerUConfig":
        """从环境变量构建 MinerU 客户端配置。

        Returns:
            已完成地址清理和数值校验的 MinerUConfig。
        """
        base_url = (os.getenv("MINERU_BASE_URL") or "http://127.0.0.1:18000").strip()
        return cls(
            enabled=_read_bool("MINERU_ENABLED", True),
            base_url=base_url.rstrip("/"),
            health_timeout_seconds=_read_positive_float("MINERU_HEALTH_TIMEOUT_SECONDS", 5.0),
            request_timeout_seconds=_read_positive_float("MINERU_REQUEST_TIMEOUT_SECONDS", 60.0),
            task_timeout_seconds=_read_positive_float("MINERU_TASK_TIMEOUT_SECONDS", 600.0),
            poll_interval_seconds=_read_positive_float("MINERU_POLL_INTERVAL_SECONDS", 2.0),
        )
