"""Markdown 标题切片方式。"""

from langchain_text_splitters import MarkdownHeaderTextSplitter

from app.server.knowledge.src.split.schemas import SplitChunk, SplitMethodConfig
from app.server.knowledge.src.split.splitters.common import build_header_mapping, extract_header_context


def split_markdown_header(
    text: str,
    config: SplitMethodConfig,
) -> list[SplitChunk]:
    """仅按 Markdown 标题切出语义大块，不继续执行长度细切。"""
    splitter = MarkdownHeaderTextSplitter(
        headers_to_split_on=build_header_mapping(config.headers),
    )
    documents = splitter.split_text(text)
    chunks: list[SplitChunk] = []
    for document in documents:
        # 标题切片返回完整语义块，不做静默截断，避免正文丢失。
        content = document.page_content.strip()
        if not content:
            continue
        # 标题层级通过 metadata.headers 暴露给下游，
        # 不再单独维护 context 字段，避免与 metadata 重复。
        headers, _ = extract_header_context(document.metadata)
        chunks.append(
            SplitChunk(
                chunk_index=len(chunks),
                content=content,
                char_count=len(content),
                metadata={
                    "headers": headers,
                    "split_method": config.type,
                },
            )
        )
    return chunks
