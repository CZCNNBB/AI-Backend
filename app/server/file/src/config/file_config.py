import os
from dataclasses import dataclass

from dotenv import load_dotenv


# 文件服务可能被独立脚本、FastAPI 路由或 Agent 中间件调用，统一在此加载 .env。
load_dotenv(override=True)


def env_positive_int(name: str, default: int) -> int:
    """读取正整数环境变量，非法值时回退默认值。

    Args:
        name: 环境变量名称。
        default: 缺失或非法时使用的默认值。

    Returns:
        大于 0 的整数配置值。
    """
    raw_value = (os.getenv(name) or "").strip()
    try:
        value = int(raw_value)
    except ValueError:
        return default
    return value if value > 0 else default


def env_bool(name: str, default: bool) -> bool:
    """读取布尔环境变量，无法识别时使用默认值。

    Args:
        name: 环境变量名称。
        default: 缺失或非法时使用的默认值。

    Returns:
        解析后的布尔值。
    """
    raw_value = (os.getenv(name) or "").strip().lower()
    if raw_value in {"true", "1", "yes", "on"}:
        return True
    if raw_value in {"false", "0", "no", "off"}:
        return False
    return default


@dataclass(frozen=True)
class FileServiceConfig:
    """文件服务的环境配置。"""

    upload_dir: str | None
    max_files_per_upload: int
    max_single_file_bytes: int
    max_total_upload_bytes: int
    upload_chunk_bytes: int
    default_read_line_count: int
    max_read_response_chars: int
    cleanup_enabled: bool = True
    temporary_retention_hours: int = 24
    cleanup_interval_seconds: int = 3600
    cleanup_batch_size: int = 100

    @classmethod
    def from_env(cls) -> "FileServiceConfig":
        """从 .env 和系统环境变量构建文件服务配置。

        Returns:
            已完成单位换算和基础校验的文件服务配置。
        """
        max_single_file_mb = env_positive_int("FILE_MAX_SINGLE_FILE_MB", 50)
        max_total_upload_mb = env_positive_int("FILE_MAX_TOTAL_UPLOAD_MB", 100)
        upload_chunk_kb = env_positive_int("FILE_UPLOAD_CHUNK_KB", 8)
        return cls(
            upload_dir=(os.getenv("AI_BACKEND_UPLOAD_DIR") or os.getenv("UPLOAD_DIR") or "").strip() or None,
            max_files_per_upload=env_positive_int("FILE_MAX_FILES_PER_UPLOAD", 10),
            max_single_file_bytes=max_single_file_mb * 1024 * 1024,
            max_total_upload_bytes=max_total_upload_mb * 1024 * 1024,
            upload_chunk_bytes=upload_chunk_kb * 1024,
            default_read_line_count=env_positive_int("FILE_DEFAULT_READ_LINE_COUNT", 200),
            max_read_response_chars=env_positive_int("FILE_MAX_READ_RESPONSE_CHARS", 24_000),
            cleanup_enabled=env_bool("FILE_CLEANUP_ENABLED", True),
            temporary_retention_hours=env_positive_int("FILE_TEMP_RETENTION_HOURS", 24),
            cleanup_interval_seconds=env_positive_int("FILE_CLEANUP_INTERVAL_SECONDS", 3600),
            cleanup_batch_size=env_positive_int("FILE_CLEANUP_BATCH_SIZE", 100),
        )
