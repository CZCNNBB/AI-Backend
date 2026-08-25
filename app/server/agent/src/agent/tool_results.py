"""Agent 工具执行结果提取工具。"""

import json
from typing import Any

from langchain_core.messages import ToolMessage


def collect_tool_results(messages: list[Any]) -> list[dict[str, Any]]:
    """从 LangGraph 最终消息列表中提取真实执行完成的工具结果。

    Args:
        messages: Agent 运行结束后的完整消息列表。

    Returns:
        工具名称、调用 ID 和结构化结果组成的列表。
    """
    results: list[dict[str, Any]] = []
    for message in messages:
        if not isinstance(message, ToolMessage):
            continue
        results.append(
            {
                "tool_name": str(message.name or ""),
                "tool_call_id": str(message.tool_call_id or ""),
                "content": _normalize_tool_content(message),
            }
        )
    return results


def _normalize_tool_content(message: ToolMessage) -> Any:
    """优先提取 MCP 结构化结果，并对 JSON 文本做安全反序列化。"""
    artifact = getattr(message, "artifact", None)
    if isinstance(artifact, dict):
        structured_content = artifact.get("structured_content")
        if structured_content is not None:
            return structured_content

    content = message.content
    if isinstance(content, str):
        return _parse_json_text(content)
    if isinstance(content, list):
        # MCP 文本块通常是单元素列表，可直接解包其 text 字段。
        if len(content) == 1 and isinstance(content[0], dict):
            text = content[0].get("text")
            if isinstance(text, str):
                return _parse_json_text(text)
        return content
    return content


def _parse_json_text(content: str) -> Any:
    """将合法 JSON 文本转换为对象，普通文本保持原样。"""
    try:
        return json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return content
