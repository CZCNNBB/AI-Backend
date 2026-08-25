"""Markdown 长度切片方式。"""

from langchain_text_splitters import MarkdownTextSplitter

from app.server.knowledge.src.split.schemas import SplitChunk, SplitMethodConfig
from app.server.knowledge.src.split.splitters.common import build_plain_chunks


def split_markdown(text: str, config: SplitMethodConfig) -> list[SplitChunk]:
    """使用 LangChain MarkdownTextSplitter 执行 Markdown 长度切片。"""
    splitter = MarkdownTextSplitter(
        chunk_size=config.chunk_size,
        chunk_overlap=config.chunk_overlap,
    )
    return build_plain_chunks(
        splitter.split_text(text),
        method=config.type,
    )
