"""
Markdown document strategy: split by headers first, then recursively split each header block.

This file only orchestrates existing primitive split methods. It does not reimplement
low-level splitting algorithms. The execution order is:

1. Denoise the original Markdown text.
2. Use markdown_header to get semantic blocks by Markdown heading level.
3. Use recursive_character inside every semantic block.
4. Attach the inherited heading hierarchy to metadata.headers only.
5. If the main path fails, fall back to the markdown primitive method.
"""

from app.server.knowledge.src.split.schemas import (
    MarkdownDocumentHeaderThenRecursiveStrategyConfig,
    SplitChunk,
    SplitMethodConfig,
)
from app.server.knowledge.src.split.splitters.common import denoise_text, normalize_heading_value
from app.server.knowledge.src.split.splitters.methods import (
    split_markdown,
    split_markdown_header,
    split_recursive_character,
)
from app.server.knowledge.src.logging_config import logger


def split_markdown_document_header_then_recursive(
    text: str,
    config: MarkdownDocumentHeaderThenRecursiveStrategyConfig,
) -> list[SplitChunk]:
    """
    组合 Markdown 标题切分和递归字符切分处理文档。

    This public strategy entrypoint handles denoise, method orchestration, metadata cleanup,
    and fallback. Header splitting, recursive character splitting, and markdown fallback are
    all delegated to primitive methods under the methods package.

    Args:
        text: Markdown document text to split.
        config: Strategy config, including heading markers, chunk size, and chunk overlap.

    Returns:
        Ordered chunks. Each chunk only carries structured heading hierarchy in metadata.headers.
    """
    try:
        # Step 1: remove common document noise before semantic splitting.
        denoised_text = denoise_text(text)

        # Step 2-4: split into semantic header blocks, recursively split each block,
        # and inherit normalized heading hierarchy to every final chunk.
        chunks = split_markdown_header_then_recursive(
            denoised_text,
            headers=config.headers,
            chunk_size=config.chunk_size,
            chunk_overlap=config.chunk_overlap,
            normalize_heading=True,
        )

        # Step 5: remove internal method markers from the composed strategy output.
        # The strategy name is exposed once on SplitOutput, not repeated in every chunk.
        for chunk in chunks:
            chunk.metadata.pop("split_method", None)
        return chunks
    except Exception as exc:  # noqa: BLE001
        # If the enhanced path fails, keep the primitive usable by falling back to markdown.
        # The failure reason is kept in logs instead of being repeated in every chunk.
        logger.warning(
            "Markdown document header recursive split failed; fallback to markdown split: %s",
            exc,
        )

        # Keep chunk length rules consistent between the main path and the fallback path.
        chunks = split_markdown(
            text,
            SplitMethodConfig(
                type="markdown",
                chunk_size=config.chunk_size,
                chunk_overlap=config.chunk_overlap,
            ),
        )

        # Remove internal method markers; the outer SplitOutput still exposes the strategy name.
        for chunk in chunks:
            chunk.metadata.pop("split_method", None)
        return chunks


def split_markdown_header_then_recursive(
    text: str,
    *,
    headers: list[str],
    chunk_size: int,
    chunk_overlap: int,
    normalize_heading: bool = False,
) -> list[SplitChunk]:
    """
    组合标题切分与递归字符切分，并保留结构化标题元数据。

    Args:
        text: Pre-cleaned Markdown text.
        headers: Markdown heading markers to recognize, for example #, ##, and ###.
        chunk_size: Target length for recursive splitting inside each header block.
        chunk_overlap: Overlap length between neighboring recursive chunks.
        normalize_heading: Whether to remove numbering prefixes from heading values.

    Returns:
        Final chunks after header block splitting, recursive detail splitting, and metadata inheritance.
    """
    # Step 1: call the markdown_header primitive method to find semantic boundaries.
    # This step must not truncate large header blocks by chunk_size.
    header_chunks = split_markdown_header(
        text,
        SplitMethodConfig(
            type="markdown_header",
            headers=headers,
        ),
    )

    # Step 2: build one recursive splitter config reused for every header block.
    recursive_config = SplitMethodConfig(
        type="recursive_character",
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )

    chunks: list[SplitChunk] = []
    for header_chunk in header_chunks:
        # Step 3: read heading hierarchy produced by markdown_header.
        raw_headers = header_chunk.metadata.get("headers", {})
        normalized_headers = (
            _normalize_headers(raw_headers)
            if normalize_heading
            else raw_headers
        )

        # Step 4: split the current header block by length. The recursive method only
        # handles text length; this strategy owns heading metadata inheritance.
        detail_chunks = split_recursive_character(
            header_chunk.content,
            recursive_config,
        )
        for detail_chunk in detail_chunks:
            # Step 5: rebuild final chunks with continuous indexes and only structured headers.
            # Display-style header paths are derived data and should be built by downstream users.
            chunks.append(
                SplitChunk(
                    chunk_index=len(chunks),
                    content=detail_chunk.content,
                    char_count=detail_chunk.char_count,
                    metadata={
                        # headers keeps structured hierarchy for filtering or path reconstruction.
                        "headers": normalized_headers,
                    },
                )
            )
    return chunks


def _normalize_headers(headers: dict[str, str]) -> dict[str, str]:
    """
    清理标题值中的编号前缀，同时保持 h1、h2 等层级键不变。
    """
    return {
        key: normalize_heading_value(value)
        for key, value in headers.items()
    }
