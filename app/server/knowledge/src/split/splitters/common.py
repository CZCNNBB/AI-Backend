"""多个切片处理器复用的公共辅助函数。"""

import re
from typing import Any

from app.server.knowledge.src.split.schemas import SplitChunk

RECURSIVE_SEPARATORS = ["\n\n", "\n", "。", "！", "？", "；", ";", ".", " ", ""]


def build_plain_chunks(
    values: list[str],
    *,
    method: str,
) -> list[SplitChunk]:
    """把文本列表标准化为带连续序号的纯切片结构。"""
    chunks: list[SplitChunk] = []
    for value in values:
        # 仅清理首尾空白；切片长度完全由具体切片方式的 chunk_size 控制。
        content = value.strip()
        if not content:
            continue
        chunks.append(
            SplitChunk(
                chunk_index=len(chunks),
                content=content,
                char_count=len(content),
                metadata={"split_method": method},
            )
        )
    return chunks


def build_header_mapping(headers: list[str]) -> list[tuple[str, str]]:
    """将 Markdown 标题符号列表转换为 LangChain 标题元数据映射。"""
    return [(header, f"h{len(header)}") for header in headers]


def extract_header_context(
    metadata: dict[str, Any],
    *,
    normalize_heading: bool = False,
) -> tuple[dict[str, str], str | None]:
    """从 LangChain metadata 提取有序标题字典和可读层级上下文。"""
    headers: dict[str, str] = {}
    context_values: list[str] = []
    for key in ("h1", "h2", "h3", "h4", "h5", "h6"):
        if key not in metadata:
            continue
        value = " ".join(str(metadata[key]).split())
        if normalize_heading:
            value = normalize_heading_value(value)
        headers[key] = value
        context_values.append(f"{key}: {value}" if normalize_heading else value)
    return headers, " > ".join(context_values) or None


def denoise_text(text: str) -> str:
    """执行从当前项目文档切片链路提炼出的启发式去噪。"""
    text = re.sub(r"\n\s*\d+\s*/\s*\d+\s*\n", "\n", text)
    text = re.sub(r"(?i)Page\s*\d+", "", text)
    text = re.sub(r"第\s*\d+\s*页", "", text)
    lines = text.split("\n")
    counts: dict[str, int] = {}
    for line in lines:
        clean_line = line.strip()
        if len(clean_line) > 4:
            counts[clean_line] = counts.get(clean_line, 0) + 1

    # 只有重复至少三次、且不像完整正文句子的行，才作为页眉页脚噪声候选。
    potential_noise = {line for line, count in counts.items() if count >= 3}
    stopwords = {
        "的", "了", "在", "是", "我", "有", "和", "就", "不", "人",
        "都", "一", "一个", "上", "也", "很", "到", "说", "要", "去",
        "你", "会", "着", "没有", "看", "好", "自己", "这",
    }
    actual_noise: set[str] = set()
    for line in potential_noise:
        if line.endswith(("。", ".", "！", "!", "？", "?", "”", '"', "）", ")")):
            continue
        if sum(1 for word in stopwords if word in line) >= 3:
            continue
        actual_noise.add(line)

    result = "\n".join(line for line in lines if line.strip() not in actual_noise)
    result = re.sub(r"\.{4,}", "...", result)
    return re.sub(r"\n{3,}", "\n\n", result).strip()


def normalize_heading_value(value: str) -> str:
    """移除标题开头的常见章节编号，并在清理为空时保留原值。"""
    clean_value = value.strip()
    normalized = re.sub(
        r"^\s*\d+(?:\.\d+){0,4}\s*[\.\-、]?\s+",
        "",
        clean_value,
    )
    normalized = re.sub(
        r"^\s*[一二三四五六七八九十]+、\s*",
        "",
        normalized,
    )
    normalized = re.sub(
        r"^\s*[（(][一二三四五六七八九十0-9]+[）)]\s*",
        "",
        normalized,
    )
    normalized = normalized.strip()
    return normalized or clean_value
