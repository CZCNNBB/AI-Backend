"""递归字符切片方式。"""

from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.server.knowledge.src.split.schemas import SplitChunk, SplitMethodConfig
from app.server.knowledge.src.split.splitters.common import RECURSIVE_SEPARATORS, build_plain_chunks


def split_recursive_character(
    text: str,
    config: SplitMethodConfig,
) -> list[SplitChunk]:
    """使用中英文友好的分隔符优先级执行递归字符切片。"""
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=config.chunk_size,
        chunk_overlap=config.chunk_overlap,
        separators=RECURSIVE_SEPARATORS,
    )
    return build_plain_chunks(
        splitter.split_text(text),
        method=config.type,
    )
