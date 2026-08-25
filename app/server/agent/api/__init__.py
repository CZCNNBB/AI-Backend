from fastapi import APIRouter

from app.server.agent.api.agent_api import router as agent_run_router
from app.server.agent.api.conversation_api import router as conversation_router
from app.server.agent.api.model_config_api import router as model_config_router
from app.server.agent.api.runs_api import router as runs_router
from app.server.agent.api.template_api import router as template_router
from app.server.agent.api.tools_api import router as tools_router


router = APIRouter()

# Agent 服务的 API 聚合出口。
# main.py 只需要挂载这一个 router，agent 模块内部新增接口时在这里继续 include 即可。
router.include_router(agent_run_router)
router.include_router(conversation_router)
router.include_router(runs_router)
router.include_router(template_router)
router.include_router(tools_router)
router.include_router(model_config_router)


__all__ = ["router"]
