"""平台 API Key 的生成和不可逆哈希工具。"""

import hashlib
import secrets


def generate_platform_api_key() -> tuple[str, str]:
    """生成高强度平台 API Key，并返回完整密钥与可展示前缀。"""
    random_part = secrets.token_urlsafe(32)
    key_prefix = f"aik_{secrets.token_hex(4)}"
    api_key = f"{key_prefix}_{random_part}"
    return api_key, key_prefix


def hash_platform_api_key(api_key: str) -> str:
    """使用 SHA-256 计算高熵平台 API Key 的不可逆摘要。"""
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()
