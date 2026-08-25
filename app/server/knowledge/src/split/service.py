"""Split 原子能力的处理器注册与统一调用服务。"""

from collections.abc import Callable
from typing import Any

from app.server.knowledge.src.split.schemas import SplitChunk, SplitMethodConfig, SplitStrategyConfig
from app.server.knowledge.src.split.splitters.methods import (
    split_character,
    split_markdown,
    split_markdown_header,
    split_qa_separator,
    split_recursive_character,
)
from app.server.knowledge.src.split.splitters.strategies import (
    split_markdown_document_header_then_recursive,
)

MethodHandler = Callable[[str, SplitMethodConfig], list[SplitChunk]]
StrategyHandler = Callable[[str, Any], list[SplitChunk]]


class SplitService:
    """注册并调度单一切片方式和组合切片策略。"""

    def __init__(self) -> None:
        """初始化处理器注册表，并注册服务内置的全部切片能力。"""
        self._method_handlers: dict[str, MethodHandler] = {}
        self._strategy_handlers: dict[str, StrategyHandler] = {}
        self._register_builtin_handlers()

    def _register_builtin_handlers(self) -> None:
        """集中注册内置切片能力，保持 service 只负责能力编排。"""
        self.register_method("markdown", split_markdown)
        self.register_method("markdown_header", split_markdown_header)
        self.register_method("recursive_character", split_recursive_character)
        self.register_method("character", split_character)
        self.register_method("qa_separator", split_qa_separator)

        self.register_strategy(
            "markdown_document_header_then_recursive",
            split_markdown_document_header_then_recursive,
        )

    def register_method(self, name: str, handler: MethodHandler) -> None:
        """注册或替换一个单一切片方式处理器。"""
        self._method_handlers[name] = handler

    def register_strategy(self, name: str, handler: StrategyHandler) -> None:
        """注册或替换一个组合切片策略处理器。"""
        self._strategy_handlers[name] = handler

    def split(
        self,
        *,
        text: str,
        method: SplitMethodConfig,
        strategy: SplitStrategyConfig | None = None,
    ) -> dict[str, Any]:
        """
        查找并调用切片处理器。

        strategy 非空时优先执行组合策略；strategy 为空时才执行 method。
        """
        clean_text = self._normalize_text(text)
        if strategy is not None:
            strategy_handler = self._strategy_handlers.get(strategy.type)
            if strategy_handler is None:
                raise ValueError(f"unsupported split strategy: {strategy.type}")
            chunks = strategy_handler(clean_text, strategy)
            return {
                "chunks": chunks,
                "split_method": None,
                "split_strategy": strategy.type,
                "effective_config": strategy.model_dump(),
            }

        method_handler = self._method_handlers.get(method.type)
        if method_handler is None:
            raise ValueError(f"unsupported split method: {method.type}")
        chunks = method_handler(clean_text, method)
        return {
            "chunks": chunks,
            "split_method": method.type,
            "split_strategy": None,
            "effective_config": method.model_dump(),
        }

    def health_check(self) -> int:
        """使用最小文本执行本地切片冒烟检查并返回切片数量。"""
        result = self.split(
            text="Split service health check.",
            method=SplitMethodConfig(
                type="recursive_character",
                chunk_size=50,
                chunk_overlap=0,
            ),
        )
        chunk_count = len(result["chunks"])
        if chunk_count != 1:
            raise ValueError(
                f"split health check result mismatch: expected 1, got {chunk_count}"
            )
        return chunk_count

    @staticmethod
    def _normalize_text(text: str) -> str:
        """清理文本首尾空白并拒绝空文本。"""
        clean_text = text.strip()
        if not clean_text:
            raise ValueError("text cannot be empty")
        return clean_text


# 模块级单例供路由和应用生命周期复用，确保注册表只初始化一次。
split_service = SplitService()
