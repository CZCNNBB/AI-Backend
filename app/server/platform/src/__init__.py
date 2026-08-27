"""业务平台模块核心实现。"""

from app.server.platform.src.dependencies import get_platform_principal
from app.server.platform.src.schemas import PlatformPrincipal
from app.server.platform.src.service import BusinessPlatformService

__all__ = ["BusinessPlatformService", "PlatformPrincipal", "get_platform_principal"]
