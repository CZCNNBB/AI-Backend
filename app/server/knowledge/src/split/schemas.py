"""Split 原子能力请求与响应模型。"""

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class SplitMethodConfig(BaseModel):
    """单一切片方式配置。"""

    type: Literal[
        "markdown",
        "markdown_header",
        "recursive_character",
        "character",
        "qa_separator",
    ] = Field(..., description="切片方式")
    chunk_size: int = Field(default=1000, ge=1, description="目标切片长度")
    chunk_overlap: int = Field(default=0, ge=0, description="相邻切片重叠长度")
    separator: str = Field(default="\n\n\n", min_length=1, description="字符或 QA 切片分隔符")
    headers: list[str] = Field(
        default_factory=lambda: ["#", "##", "###", "####"],
        min_length=1,
        description="Markdown 标题切片级别",
    )
    @model_validator(mode="after")
    def validate_chunk_overlap(self) -> "SplitMethodConfig":
        """校验重叠长度必须小于目标切片长度。"""
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("chunk_overlap must be less than chunk_size")
        return self


class MarkdownDocumentHeaderThenRecursiveStrategyConfig(BaseModel):
    """先按 Markdown 标题切块、再递归细切的通用文档策略。"""

    type: Literal["markdown_document_header_then_recursive"] = Field(
        ...,
        description="Markdown 文档标题切块后递归细切策略",
    )
    chunk_size: int = Field(default=1000, ge=1, description="递归细切目标长度")
    chunk_overlap: int = Field(default=200, ge=0, description="递归细切重叠长度")
    headers: list[str] = Field(
        default_factory=lambda: ["#", "##", "###", "####"],
        min_length=1,
        description="参与层级切片的 Markdown 标题",
    )
    @model_validator(mode="after")
    def validate_chunk_overlap(
        self,
    ) -> "MarkdownDocumentHeaderThenRecursiveStrategyConfig":
        """校验递归细切的重叠长度必须小于目标长度。"""
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("chunk_overlap must be less than chunk_size")
        return self


# 当前仅保留“Markdown 标题切块后递归细切”策略。
SplitStrategyConfig = MarkdownDocumentHeaderThenRecursiveStrategyConfig


class SplitInput(BaseModel):
    """切片预览输入；正式文件读取由后续 IngestionService 负责。"""

    text: str = Field(..., min_length=1, description="待切片的 Markdown 或纯文本")
    split_method: SplitMethodConfig | None = Field(
        default=None,
        description="单一切片方式；split_strategy 为空时使用",
    )
    split_strategy: SplitStrategyConfig | None = Field(
        default=None,
        description="组合切片策略；传入后优先于 split_method",
    )

class SplitChunk(BaseModel):
    """与业务身份无关的纯切片输出。"""

    chunk_index: int = Field(..., ge=0, description="本次切片结果中的顺序")
    content: str = Field(..., description="切片正文")
    char_count: int = Field(..., ge=0, description="切片正文字符数")
    metadata: dict[str, Any] = Field(default_factory=dict, description="切片过程产生的附加信息")


class SplitOutput(BaseModel):
    """Split 任务输出参数。"""

    chunk_count: int = Field(..., ge=0, description="切片数量")
    chunks: list[SplitChunk] = Field(default_factory=list, description="纯切片结果")
    split_method: str | None = Field(default=None, description="实际使用的单一切片方式")
    split_strategy: str | None = Field(default=None, description="实际使用的组合切片策略")
    effective_config: dict[str, Any] = Field(..., description="本次实际生效的切片配置")
