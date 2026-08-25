from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.common.db.postgres_db import get_postgres_engine
from app.common.schemas.result import Result
from app.server.agent.src.mcp import MCPService
from app.server.agent.src.mcp.schemas import (
    AgentMCPToolDeleteRequest,
    AgentMCPToolDetailRequest,
    AgentMCPToolInvokeRequest,
    AgentMCPToolSearchRequest,
    AgentMCPToolSearchResponse,
    AgentMCPToolSyncRequest,
    AgentMCPToolSyncResponse,
    AgentMCPToolTestRequest,
    AgentMCPToolTestResponse,
    AgentMCPToolUpsertRequest,
    AgentMCPToolView,
)


router = APIRouter(prefix="/mcp")
mcp_service = MCPService()


@router.post("/upsert", response_model=Result[AgentMCPToolView], summary="新增或更新 MCP 工具")
def upsert_mcp_tool(
    request: AgentMCPToolUpsertRequest,
    db: Session = Depends(get_postgres_engine),
):
    """新增或更新平台可接入的 MCP 工具配置。"""
    result = mcp_service.upsert_tool(db, request)
    return Result.success(result)


@router.post("/detail", response_model=Result[AgentMCPToolView | None], summary="查询 MCP 工具详情")
def get_mcp_tool_detail(
    request: AgentMCPToolDetailRequest,
    db: Session = Depends(get_postgres_engine),
):
    """根据 mcp_code 查询 MCP 工具详情。"""
    result = mcp_service.get_tool(db, request)
    return Result.success(result)


@router.post("/search", response_model=Result[AgentMCPToolSearchResponse], summary="查询 MCP 工具列表")
def search_mcp_tools(
    request: AgentMCPToolSearchRequest,
    db: Session = Depends(get_postgres_engine),
):
    """分页查询平台 MCP 工具配置列表。"""
    result = mcp_service.search_tools(db, request)
    return Result.success(result)


@router.post("/delete", response_model=Result[int], summary="批量删除 MCP 工具")
def delete_mcp_tools(
    request: AgentMCPToolDeleteRequest,
    db: Session = Depends(get_postgres_engine),
):
    """根据 mcp_code 列表批量删除 MCP 工具配置。"""
    deleted = mcp_service.delete_tools(db, request)
    return Result.success(deleted)


@router.post("/test", response_model=Result[AgentMCPToolTestResponse], summary="测试 MCP 工具连接")
async def test_mcp_tools(
    request: AgentMCPToolTestRequest,
    db: Session = Depends(get_postgres_engine),
):
    """测试 MCP 工具或临时 MCP 服务地址是否可连接，并返回远程工具摘要。"""
    result = await mcp_service.test_tools(db, request)
    return Result.success(result)


@router.post("/sync", response_model=Result[AgentMCPToolSyncResponse], summary="同步 MCP 工具")
async def sync_mcp_tools(
    request: AgentMCPToolSyncRequest,
    db: Session = Depends(get_postgres_engine),
):
    """从指定 MCP 服务地址同步工具列表到平台 MCP 工具表。"""
    result = await mcp_service.sync_tools(db, request)
    return Result.success(result)


@router.post("/invoke", response_model=Result[object], summary="测试调用 MCP 工具")
async def invoke_mcp_tool(
    request: AgentMCPToolInvokeRequest,
    db: Session = Depends(get_postgres_engine),
):
    """直接调用一个已保存的 MCP 工具，主要用于工具管理页联调。"""
    result = await mcp_service.invoke_tool(db, request)
    return Result.success(result)
