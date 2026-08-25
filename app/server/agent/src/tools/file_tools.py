import json

from langchain_core.tools import tool
from langgraph.prebuilt.tool_node import ToolRuntime

from app.common.db.postgres_db import get_db_session
from app.server.file.src.service.file_service import FileService


def _get_allowed_file_ids(runtime: ToolRuntime) -> set[str]:
    """从 ToolRuntime.context 中读取本次 Agent 允许访问的附件 ID。"""
    context = getattr(runtime, "context", None) if runtime is not None else None
    if isinstance(context, dict):
        file_ids = context.get("file_ids") or []
    elif hasattr(context, "model_dump"):
        file_ids = context.model_dump().get("file_ids") or []
    else:
        file_ids = []
    return {str(file_id).strip() for file_id in file_ids if str(file_id or "").strip()}


@tool("read_uploaded_file")
async def read_uploaded_file(
    file_id: str,
    runtime: ToolRuntime,
    start_line: int | None = None,
    end_line: int | None = None,
) -> str:
    """按行范围读取本次请求中用户上传的单个文件。

    每次只能读取一个白名单 file_id。未提供行范围时默认读取前 200 行；
    读取结果过长会自动截断，Agent 应缩小行范围后再次调用。

    Args:
        file_id: 要读取的单个附件文件 ID。
        runtime: LangGraph 注入的工具运行时。
        start_line: 可选起始行号，从 1 开始。
        end_line: 可选结束行号，包含该行。

    Returns:
        带行号的文件内容片段，或明确的错误说明。
    """
    cleaned_file_id = str(file_id or "").strip()
    if not cleaned_file_id:
        return "错误：file_id 不能为空。"
    if cleaned_file_id not in _get_allowed_file_ids(runtime):
        return "错误：该文件不在本次请求允许访问的附件列表中，不能读取。"

    # FileService 会复用已生成的 content.md、文本内容源和 Outline 缓存。
    with get_db_session() as db:
        result = await FileService().read_file_lines(
            db,
            file_id=cleaned_file_id,
            start_line=start_line,
            end_line=end_line,
        )

    if not result.content.strip():
        return f"文件ID：{result.file_id}\n文件名：{result.original_name}\n{result.message or '没有可用文本内容。'}"
    return (
        f"文件ID：{result.file_id}\n"
        f"文件名：{result.original_name}\n"
        f"内容类型：{result.content_type}\n"
        f"行范围：{result.start_line}-{result.end_line} / 共 {result.total_lines} 行\n"
        f"读取已截断：{result.truncated}\n"
        f"提示：{result.message or '无'}\n\n"
        f"{result.content}"
    )

@tool("search_uploaded_files")
async def search_uploaded_files(
    keyword: str,
    runtime: ToolRuntime,
    max_results: int = 20,
    context_lines: int = 2,
) -> str:
    """在本次请求授权的全部附件中按关键词检索内容。

    用于定位关键词出现在哪个文件、哪一行。不要把文件 ID 作为参数传入；
    工具会从运行时上下文自动获取本次允许访问的文件范围。找到命中后，
    应继续调用 read_uploaded_file 按行范围精读正文。

    Args:
        keyword: 要检索的关键词；英文匹配忽略大小写。
        runtime: LangGraph 注入的工具运行时。
        max_results: 最多返回多少条命中，范围为 1 到 50。
        context_lines: 每条命中前后返回多少行上下文，范围为 0 到 5。

    Returns:
        JSON 格式的命中列表、行号、上下文及跳过文件说明。
    """
    cleaned_keyword = str(keyword or "").strip()
    if not cleaned_keyword:
        return "错误：keyword 不能为空。"

    allowed_file_ids = _get_allowed_file_ids(runtime)
    if not allowed_file_ids:
        return "错误：本次请求没有可检索的附件。"

    # 白名单只来自 ToolRuntime，模型不能借由工具参数扩大附件检索范围。
    with get_db_session() as db:
        result = await FileService().search_file_contents(
            db,
            file_ids=sorted(allowed_file_ids),
            keyword=cleaned_keyword,
            max_results=max_results,
            context_lines=context_lines,
        )
    return json.dumps(result, ensure_ascii=False)
