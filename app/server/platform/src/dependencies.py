"""FastAPI 业务平台身份认证依赖。"""

from typing import Annotated

from fastapi import Header

from app.common.core.exceptions import BusinessException
from app.common.db.postgres_db import postgres_transaction
from app.server.platform.src.schemas import PlatformPrincipal
from app.server.platform.src.service import BusinessPlatformService


platform_service = BusinessPlatformService()


def get_platform_principal(
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> PlatformPrincipal:
    """使用独立短事务校验平台 API Key，并返回可信业务平台身份。

    身份认证会发生在业务接口执行前。这里不能使用请求级 ``yield Session``，
    否则 SSE 等流式响应结束前依赖不会释放，认证查询占用的数据库连接也可能
    被一同长期持有。
    """
    if not x_api_key:
        raise BusinessException(code=401, msg="请求头缺少 X-API-Key")

    # API Key 认证只需要一次查询。离开上下文后立即提交并关闭 Session，
    # 后续 Agent/LLM/MCP 流式执行不会继续占用这条业务数据库连接。
    with postgres_transaction() as db:
        principal = platform_service.authenticate_api_key(db, x_api_key)
    return principal
