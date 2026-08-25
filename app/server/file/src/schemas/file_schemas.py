from typing import Any

from pydantic import BaseModel, Field


class UploadedFileView(BaseModel):
    """上传文件返回视图。"""

    file_id: str = Field(..., description="文件 ID")
    original_name: str = Field(..., description="原始文件名")
    stored_name: str = Field(..., description="服务端存储文件名")
    extension: str = Field(default="", description="文件扩展名")
    mime_type: str | None = Field(default=None, description="MIME 类型")
    size_bytes: int = Field(default=0, description="文件大小，单位字节")
    status: str = Field(default="uploaded", description="文件状态")
    content_type: str = Field(default="pending", description="内容类型")
    conversion_status: str = Field(default="pending", description="转换状态")
    converter_name: str | None = Field(default=None, description="最近一次使用的转换器")
    created_at: str | None = Field(default=None, description="创建时间")
    updated_at: str | None = Field(default=None, description="更新时间")


class FileUploadResponse(BaseModel):
    """文件上传响应。"""

    files: list[UploadedFileView] = Field(default_factory=list, description="已上传文件列表")


class FileDetailRequest(BaseModel):
    """查询文件详情请求。"""

    file_id: str = Field(..., min_length=1, description="文件 ID")


class FileParseRequest(BaseModel):
    """构建文件可读内容源请求。"""

    file_id: str = Field(..., min_length=1, description="文件 ID")
    force: bool = Field(default=False, description="是否强制重新转换")


class FileParseResponse(BaseModel):
    """文件可读内容源响应。"""

    file_id: str = Field(..., description="文件 ID")
    original_name: str = Field(..., description="原始文件名")
    content_type: str = Field(default="pending", description="内容类型")
    content: str = Field(default="", description="解析后的文本内容")
    content_length: int = Field(default=0, description="文本长度")
    conversion_status: str = Field(default="success", description="转换状态")
    outline: dict[str, Any] = Field(default_factory=dict, description="内容目录与预览")


class FileReadResult(BaseModel):
    """Agent 按行读取文件后的结果。"""

    file_id: str = Field(..., description="文件 ID")
    original_name: str = Field(..., description="原始文件名")
    content_type: str = Field(..., description="内容类型")
    content: str = Field(default="", description="带行号的文本片段")
    start_line: int | None = Field(default=None, description="实际起始行号")
    end_line: int | None = Field(default=None, description="实际结束行号")
    total_lines: int = Field(default=0, description="内容总行数")
    truncated: bool = Field(default=False, description="输出是否被长度保护截断")
    message: str | None = Field(default=None, description="读取提示或错误说明")


class FileDeleteRequest(BaseModel):
    """删除文件请求。"""

    file_ids: list[str] = Field(..., min_length=1, description="待删除文件 ID 列表")


class FileDeleteResponse(BaseModel):
    """删除文件响应。"""

    deleted: int = Field(default=0, description="删除数量")
    file_ids: list[str] = Field(default_factory=list, description="已删除文件 ID")
