"""指定分隔符字符切片方式。"""

from langchain_text_splitters import CharacterTextSplitter

from app.server.knowledge.src.split.schemas import SplitChunk, SplitMethodConfig
from app.server.knowledge.src.split.splitters.common import build_plain_chunks


def split_character(text: str, config: SplitMethodConfig) -> list[SplitChunk]:
    """使用 LangChain CharacterTextSplitter 按指定分隔符切片。"""
    splitter = CharacterTextSplitter(
        separator=config.separator,
        chunk_size=config.chunk_size,
        chunk_overlap=config.chunk_overlap,
    )
    return build_plain_chunks(
        splitter.split_text(text),
        method=config.type,
    )
