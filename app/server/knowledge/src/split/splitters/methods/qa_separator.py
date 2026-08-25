"""QA 分隔符切片方式。"""

from app.server.knowledge.src.split.schemas import SplitChunk, SplitMethodConfig
from app.server.knowledge.src.split.splitters.common import build_plain_chunks


def split_qa_separator(text: str, config: SplitMethodConfig) -> list[SplitChunk]:
    """按 QA 分隔符直接切块，严格保留一问一答边界。"""
    blocks = [
        block.strip()
        for block in text.split(config.separator)
        if block.strip()
    ]
    return build_plain_chunks(
        blocks,
        method=config.type,
    )
