import logging
from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelRequest, ModelResponse
from langchain_core.messages import SystemMessage

from app.common.db.postgres_db import get_db_session
from app.server.agent.src.graph.state import CareerAgentState
from app.server.file.src.service.file_service import FileService

logger = logging.getLogger(__name__)


class FileContextMiddleware(AgentMiddleware[CareerAgentState]):
    """附件上下文中间件，负责把文件清单和 Outline 注入模型上下文。"""

    def __init__(self, file_service: FileService | None = None):
        """初始化附件上下文中间件。"""
        self.file_service = file_service or FileService()
        # Agent 每次请求都会重新组装中间件实例；该缓存只覆盖当前一次 Agent Run。
        self._file_list_text: str | None = None
        self._cached_file_ids: tuple[str, ...] | None = None

    def _get_runtime_context(self, request: ModelRequest) -> Any:
        """读取 LangChain runtime context。"""
        return getattr(request.runtime, "context", None)

    def _get_file_ids(self, request: ModelRequest) -> list[str]:
        """从 runtime context 中读取附件文件 ID 列表。"""
        context = self._get_runtime_context(request)
        file_ids = context.get("file_ids") if isinstance(context, dict) else getattr(context, "file_ids", [])
        return [str(file_id).strip() for file_id in (file_ids or []) if str(file_id or "").strip()]

    def _get_run_id(self, request: ModelRequest) -> str:
        """从 runtime context 中读取 run_id，方便日志排查。"""
        context = self._get_runtime_context(request)
        return str(context.get("run_id") or "") if isinstance(context, dict) else str(getattr(context, "run_id", "") or "")

    def _format_outline(self, outline: object) -> list[str]:
        """把单个文件 Outline 格式化为模型可读文本。"""
        if not isinstance(outline, dict):
            return []
        lines: list[str] = []
        total_lines = int(outline.get("total_lines") or 0)
        total_heading_count = int(outline.get("total_heading_count") or 0)
        displayed_heading_count = len(outline.get("entries") or [])
        if total_lines:
            lines.append(
                f"  - 文档总长度：{total_lines} 行；标题总数：{total_heading_count}；"
                f"已展示：{displayed_heading_count} 个标题。"
            )
        for entry in outline.get("entries") or []:
            if isinstance(entry, dict):
                lines.append(f"  - L{entry.get('line_number')}: {entry.get('title')}")
        if not lines and outline.get("preview"):
            lines.append("  Preview:")
            lines.extend(f"  - {item}" for item in outline["preview"])
        if outline.get("truncated"):
            omitted_heading_count = int(outline.get("omitted_heading_count") or 0)
            lines.append(
                f"  - Outline 已截断，后续还有 {omitted_heading_count} 个标题未展示；"
                f"文档共 {total_lines} 行，请使用 start_line、end_line 分段读取。"
            )
        if outline.get("message"):
            lines.append(f"  - {outline['message']}")
        return lines

    def _format_file_list(self, summaries: list[dict[str, object]]) -> str:
        """把文件摘要格式化为模型可读清单。"""
        lines: list[str] = []
        for index, item in enumerate(summaries, start=1):
            file_id = str(item.get("file_id") or "")
            if item.get("status") in {"missing", "failed"}:
                lines.append(f"{index}. file_id={file_id}; status={item.get('status')}; error={item.get('error') or ''}")
                continue
            lines.append(
                f"{index}. file_id={file_id}; name={item.get('original_name')}; "
                f"extension={item.get('extension')}; content_type={item.get('content_type')}; "
                f"conversion_status={item.get('conversion_status')}"
            )
            lines.extend(self._format_outline(item.get("outline")))
        return "\n".join(lines)

    async def _build_file_list_text(self, file_ids: list[str]) -> str:
        """构建本次请求的附件清单与 Outline。"""
        with get_db_session() as db:
            summaries = await self.file_service.build_agent_file_summaries(db, file_ids)
        return self._format_file_list(summaries)

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        """在每次模型调用前注入附件地图，不注入附件全文。"""
        file_ids = self._get_file_ids(request)
        if not file_ids:
            return await handler(request)

        normalized_file_ids = tuple(file_ids)
        if self._cached_file_ids != normalized_file_ids:
            # 第一次模型调用时抽 Outline；同一次 Agent Run 的后续模型调用直接复用。
            self._file_list_text = await self._build_file_list_text(file_ids)
            self._cached_file_ids = normalized_file_ids

        file_list_text = self._file_list_text or ""
        if not file_list_text:
            return await handler(request)

        logger.info("附件地图注入成功: run_id=%s file_ids=%s", self._get_run_id(request), len(file_ids))
        inserted = (
            "\n\n<uploaded_files>\n"
            "用户本轮上传了以下附件。这里仅提供文件清单、Outline 和预览，不包含文件正文。\n"
            "如需查看、总结、分析附件内容，必须先调用 read_uploaded_file。\n"
            "如需在多个附件或长文档中定位关键词，使用 search_uploaded_files，再按返回行号精读。\n"
            "read_uploaded_file 每次只能读取一个 file_id；长文档必须使用 start_line、end_line 分段读取。\n"
            "不得在未读取文件内容前声称已经查看或分析附件正文。\n\n"
            f"{file_list_text}\n"
            "</uploaded_files>"
        )
        current_prompt = getattr(request.system_message, "content", "")
        return await handler(request.override(system_message=SystemMessage(content=f"{current_prompt}{inserted}")))
