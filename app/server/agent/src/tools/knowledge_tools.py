"""Agent 知识库检索内部工具。"""

from typing import Any

from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langgraph.prebuilt.tool_node import ToolRuntime
from langgraph.types import Command

from app.common.db.postgres_db import get_db_session
from app.server.knowledge.src.repositories import KnowledgeBaseRepository
from app.server.knowledge.src.retrieval.schemas import RerankConfig, RetrievalConfig, RetrievalInput
from app.server.knowledge.src.services.knowledge_service import knowledge_service


def _get_runtime_value(runtime: ToolRuntime, key: str, default: Any = None) -> Any:
    """从 ToolRuntime.context 中读取系统可信运行参数。"""
    context = getattr(runtime, "context", None) if runtime is not None else None
    if isinstance(context, dict):
        return context.get(key, default)
    if hasattr(context, "model_dump"):
        return context.model_dump().get(key, default)
    return getattr(context, key, default)


def _build_tool_message(runtime: ToolRuntime, content: str) -> ToolMessage:
    """构建与当前工具调用关联的 ToolMessage。"""
    tool_call_id = getattr(runtime, "tool_call_id", None) if runtime is not None else None
    return ToolMessage(content=content, tool_call_id=str(tool_call_id or "search_knowledge_base"))


def _resolve_collection_names(knowledge_base_ids: list[str]) -> list[str]:
    """校验知识库白名单并解析为可检索的 Milvus Collection 名称。"""
    repository = KnowledgeBaseRepository()
    with get_db_session() as db:
        records = [
            repository.get_by_knowledge_id(db, knowledge_id)
            for knowledge_id in knowledge_base_ids
        ]

    unavailable_ids = [
        knowledge_id
        for knowledge_id, record in zip(knowledge_base_ids, records, strict=True)
        if record is None or record.status != "active"
    ]
    if unavailable_ids:
        raise ValueError("以下知识库不存在或未启用：" + "、".join(unavailable_ids))

    return [record.collection_name for record in records if record is not None]


def _format_retrieval_context(query: str, result: Any) -> str:
    """把知识库检索结果转换为可注入系统提示词的证据文本。"""
    lines = [f"知识库查询：{query}", f"命中数量：{result.result_count}"]
    for index, item in enumerate(result.results, start=1):
        lines.extend(
            [
                "",
                f"[证据 {index}]",
                f"来源文件：{item.source}",
                f"文件 ID：{item.file_id}",
                f"相关度：{item.score:.6f}",
                f"正文：\n{item.content}",
            ]
        )
    return "\n".join(lines)


@tool("search_knowledge_base")
async def search_knowledge_base(
    query: str,
    runtime: ToolRuntime,
    top_k: int = 5,
) -> Command:
    """检索当前 Agent 模板已挂载的知识库。

    知识库范围由系统从 Runtime Context 自动注入，模型只需要提供自然语言查询。
    工具使用混合检索；Rerank 模型后续由调用配置明确指定，检索证据不会直接塞进普通工具消息，
    而是写入 LangGraph retrieval_context，并在下一轮模型调用前注入系统提示词。

    Args:
        query: 要在知识库中检索的完整问题或关键词。
        runtime: LangGraph 注入的工具运行时，包含知识库访问白名单和当前 run_id。
        top_k: 最多保留的检索结果数量，范围为 1 到 10。

    Returns:
        Command，写入本轮检索上下文和简短工具执行结果。
    """
    cleaned_query = str(query or "").strip()
    if not cleaned_query:
        raise ValueError("query 不能为空")

    safe_top_k = max(1, min(int(top_k), 10))
    knowledge_enabled = bool(_get_runtime_value(runtime, "knowledge_enabled", False))
    knowledge_base_ids = [
        str(value).strip()
        for value in (_get_runtime_value(runtime, "knowledge_base_ids", []) or [])
        if str(value or "").strip()
    ]
    if not knowledge_enabled:
        raise ValueError("当前 Agent 未启用知识库检索能力")
    if not knowledge_base_ids:
        raise ValueError("当前 Agent 未配置可访问的知识库")

    collection_names = _resolve_collection_names(knowledge_base_ids)
    result = await knowledge_service.retrieve(
        RetrievalInput(
            collection_list=collection_names,
            query=cleaned_query,
            retrieval_config=RetrievalConfig(
                mode="hybrid",
                top_k=safe_top_k,
                fetch_k=max(safe_top_k * 3, 10),
                similarity_threshold=0.2,
            ),
            rerank_config=RerankConfig(enable=False),
        )
    )

    run_id = str(_get_runtime_value(runtime, "run_id", "") or "")
    if result.result_count == 0:
        message = "知识库检索完成，但没有找到足够相关的内容。"
        return Command(update={"messages": [_build_tool_message(runtime, message)]})

    retrieval_context = _format_retrieval_context(cleaned_query, result)
    return Command(
        update={
            "retrieval_context": [{"run_id": run_id, "content": retrieval_context}],
            "messages": [
                _build_tool_message(
                    runtime,
                    f"知识库检索成功，共找到 {result.result_count} 条相关证据，内容已注入下一轮模型上下文。",
                )
            ],
        }
    )
