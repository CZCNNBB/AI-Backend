from typing import Annotated

from fastapi import APIRouter, Depends, Header
from sqlmodel import Session

from app.common.db.postgres_db import get_postgres_engine
from app.common.schemas.result import Result
from app.server.fastmcp.src.schemas import (
    MCPToolDeleteRequest,
    MCPToolDetailRequest,
    MCPToolEligibleRequest,
    MCPToolInvokeRequest,
    MCPToolPublishRequest,
    MCPToolSearchRequest,
    MCPToolSearchResponse,
    MCPToolTestRequest,
    MCPToolTestResponse,
    MCPToolUpsertRequest,
    MCPToolView,
)
from app.server.fastmcp.src.service import MCPToolService


router = APIRouter(prefix="/tools")
mcp_tool_service = MCPToolService()


@router.post("/upsert", response_model=Result[MCPToolView], summary="保存 API 转换型 MCP Tool")
def upsert_mcp_tool(
    request: MCPToolUpsertRequest,
    db: Session = Depends(get_postgres_engine),
):
    """保存 HTTP API、参数映射和认证配置，并按状态热更新 Tool。"""
    result = mcp_tool_service.upsert_tool(db, request)
    return Result.success(result)


@router.post("/detail", response_model=Result[MCPToolView | None], summary="查询 MCP Tool 详情")
def get_mcp_tool_detail(
    request: MCPToolDetailRequest,
    db: Session = Depends(get_postgres_engine),
):
    """根据工具名查询完整 HTTP API 转换配置。"""
    result = mcp_tool_service.get_tool(db, request)
    return Result.success(result)


@router.post("/search", response_model=Result[MCPToolSearchResponse], summary="查询 MCP Tool 列表")
def search_mcp_tools(
    request: MCPToolSearchRequest,
    db: Session = Depends(get_postgres_engine),
):
    """分页查询平台管理的 API 转换型 MCP Tool。"""
    result = mcp_tool_service.search_tools(db, request)
    return Result.success(result)


@router.post("/eligible", response_model=Result[list[MCPToolView]], summary="查询 Agent 可挂载的 MCP Tool")
def list_eligible_mcp_tools(
    request: MCPToolEligibleRequest,
    db: Session = Depends(get_postgres_engine),
):
    """根据 Agent 绑定的平台集合返回同时覆盖这些平台的已发布工具。"""
    return Result.success(mcp_tool_service.list_eligible_tools(db, request))


@router.post("/delete", response_model=Result[int], summary="批量删除 MCP Tool")
def delete_mcp_tools(
    request: MCPToolDeleteRequest,
    db: Session = Depends(get_postgres_engine),
):
    """批量删除配置，并从当前 FastMCP 进程热移除 Tool。"""
    deleted = mcp_tool_service.delete_tools(db, request)
    return Result.success(deleted)


@router.post("/publish", response_model=Result[MCPToolView], summary="发布或停用 MCP Tool")
def publish_mcp_tool(
    request: MCPToolPublishRequest,
    db: Session = Depends(get_postgres_engine),
):
    """切换工具发布状态，并立即更新当前 FastMCP Registry。"""
    result = mcp_tool_service.publish_tool(db, request)
    return Result.success(result)


@router.post("/test", response_model=Result[MCPToolTestResponse], summary="测试目标 HTTP API")
async def test_mcp_tool(
    request: MCPToolTestRequest,
    business_authorization: Annotated[
        str | None,
        Header(alias="X-Business-Authorization"),
    ] = None,
    db: Session = Depends(get_postgres_engine),
):
    """使用测试参数验证请求组装、认证配置和目标 API 连通性。"""
    result = await mcp_tool_service.test_tool(
        db,
        request,
        business_authorization=business_authorization,
    )
    return Result.success(result)


@router.post("/invoke", response_model=Result[object], summary="调试调用已发布 MCP Tool")
async def invoke_mcp_tool(
    request: MCPToolInvokeRequest,
    business_authorization: Annotated[
        str | None,
        Header(alias="X-Business-Authorization"),
    ] = None,
    db: Session = Depends(get_postgres_engine),
):
    """直接执行一个已发布 Tool，主要用于管理页面联调。"""
    result = await mcp_tool_service.invoke_tool(
        db,
        request,
        business_authorization=business_authorization,
    )
    return Result.success(result)
