import json
from typing import Any

from typing import Annotated

from fastapi import APIRouter, Depends, Header
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse
from sqlmodel import Session

from app.common.db.postgres_db import get_postgres_engine
from app.common.schemas.result import Result
from app.server.agent.src.agent import AgentMessageService, AgentService
from app.server.agent.src.checkpoint import agent_checkpoint_service
from app.server.agent.src.model import ModelConfigService
from app.server.agent.src.model.schemas import ModelConfigSearchRequest
from app.server.agent.src.schemas.request import AgentMessageRequest
from app.server.agent.src.schemas.response import AgentCapabilityResponse, AgentRunResponse, ModelConfigResponse
from app.server.agent.src.tools.schemas import AgentToolInfo
from app.server.fastmcp.src.schemas import MCPToolSearchRequest
from app.server.fastmcp.src.service import MCPToolService
from app.server.platform.src import PlatformPrincipal, get_platform_principal


router = APIRouter()
# 主 AgentService 和 FastAPI lifespan 共用同一个 Checkpointer 服务，确保每个 Worker 只有一个池。
agent_service = AgentService(checkpoint_service=agent_checkpoint_service)
agent_message_service = AgentMessageService(agent_service=agent_service)
model_config_service = ModelConfigService()
mcp_tool_service = MCPToolService()


@router.get("/health", response_model=Result[dict], summary="Agent 服务健康检查")
def agent_health():
    """检查 Agent 服务是否已经挂载。"""
    return Result.success({"service": "agent", "status": "ok"})


@router.get("/model/config", response_model=Result[ModelConfigResponse], summary="查询当前模型资源池摘要")
def get_current_model_config(db: Session = Depends(get_postgres_engine)):
    """查询当前模型资源池摘要，用于兼容旧的前端健康展示入口。"""
    result = model_config_service.search_models(
        db,
        ModelConfigSearchRequest(page=1, page_size=100, enabled=True),
    )
    available_models = [item.model_code for item in result.items]
    return Result.success(
        ModelConfigResponse(
            available_models=available_models,
            chat_models=[item.model_code for item in result.items if item.model_type == "chat"],
            embedding_models=[item.model_code for item in result.items if item.model_type == "embedding"],
            rerank_models=[item.model_code for item in result.items if item.model_type == "rerank"],
        )
    )


@router.get("/capabilities", response_model=Result[AgentCapabilityResponse], summary="查询 Agent 服务能力")
def get_agent_capabilities(db: Session = Depends(get_postgres_engine)):
    """查询 Agent 服务当前已经挂载的能力模块。"""
    internal_tools = agent_service.tool_service.list_tool_details()
    mcp_tools = _list_mcp_tool_details(db)
    all_tools = internal_tools + mcp_tools
    return Result.success(
        AgentCapabilityResponse(
            service_name="agent",
            modules=[
                "agent",
                "model",
                "schemas",
                "prompts",
                "tools",
                "templates",
                "runtime",
                "middlewares",
                "memory",
                "checkpoint",
                "graph",
            ],
            enabled_features=[
                "openai_compatible_chat_model",
                "model_config_management",
                "embedding_model_placeholder",
                "prompt_rendering",
                "agent_template_management",
                "middleware_factory",
                "runtime_context_schema",
                "memory_placeholder",
                "postgres_checkpointer",
                "graph_state_schema",
                "mcp_external_tools",
                "knowledge_retrieval_internal_tool",
            ],
            registered_tools=[tool.name for tool in all_tools if tool.template_selectable],
            tools=all_tools,
        )
    )


def _list_mcp_tool_details(db: Session) -> list[AgentToolInfo]:
    """查询已启用 MCP 工具，并转换为工具管理页可展示结构。"""
    result = mcp_tool_service.search_tools(
        db,
        MCPToolSearchRequest(status="enabled", page=1, page_size=100),
    )
    return [
        AgentToolInfo(
            name=item.name,
            description=item.description or "",
            group="mcp",
            invokable=True,
            template_selectable=True,
            activation_mode="template",
            invoke_note="MCP 外部工具，名称同时作为 Agent 配置中的稳定标识。",
            args_schema=_normalize_tool_schema(item.input_schema),
        )
        for item in result.items
    ]


def _normalize_tool_schema(schema: dict[str, Any] | None) -> dict[str, Any]:
    """把 MCP 工具参数 schema 统一成前端表单期望的 JSON Schema 结构。"""
    if not schema:
        return {}
    if "properties" in schema:
        return schema
    return {"type": "object", "properties": schema, "required": []}


def _format_sse_event(event: dict[str, Any]) -> str:
    """将平台事件字典格式化为 SSE 文本。"""
    event_type = str(event.get("type") or "message")
    payload = json.dumps(jsonable_encoder(event), ensure_ascii=False)
    return f"event: {event_type}\ndata: {payload}\n\n"


@router.post("/messages", response_model=Result[AgentRunResponse], summary="发送 Agent 消息")
async def send_agent_message(
    request: AgentMessageRequest,
    principal: PlatformPrincipal = Depends(get_platform_principal),
    business_authorization: Annotated[
        str | None,
        Header(alias="X-Business-Authorization"),
    ] = None,
):
    """统一 Agent 消息入口。

    前端只需要调用该接口：
    - 当前会话没有待恢复中断时，后端自动创建新的 Agent 运行。
    - 当前会话存在 interrupted 运行时，后端自动转换为 Command(resume=...) 恢复执行。

    注意：该长耗时接口不能注入请求级数据库 Session。AgentMessageService 会在
    路由、运行开始和运行结束阶段分别创建短事务，SSE 流式执行期间不持有业务连接。
    """
    if request.stream:
        async def event_generator():
            """按 SSE 格式逐条产出 Agent 消息处理事件。"""
            async for event in agent_message_service.stream_message(
                request,
                principal=principal,
                business_authorization=business_authorization,
            ):
                yield _format_sse_event(event)

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    result = await agent_message_service.run_message(
        request,
        principal=principal,
        business_authorization=business_authorization,
    )
    return Result.success(result)
