from pathlib import Path


class OcrService:
    """OCR 能力边界，当前仅预留 MinerU 接入位置。"""

    def is_available(self) -> bool:
        """返回当前 OCR 是否已经接入并可用。

        Returns:
            当前版本固定返回 False，后续 MinerU 服务就绪后改为实际健康状态。
        """
        return False

    def get_unavailable_message(self, file_kind: str) -> str:
        """构建 OCR 尚未启用时返回给 Agent 的统一提示。

        Args:
            file_kind: 文件类型，例如 image 或 scanned_pdf。

        Returns:
            OCR 未启用说明。
        """
        return f"当前 {file_kind} OCR 能力尚未启用，后续将接入 MinerU 后处理。"

    def build_placeholder_outline(self, file_kind: str) -> dict[str, object]:
        """构建 OCR 未启用文件使用的占位 Outline。

        Args:
            file_kind: 文件类型，例如 image。

        Returns:
            带 OCR 状态和提示信息的空 Outline。
        """
        return {
            "entries": [],
            "preview": [],
            "total_lines": 0,
            "total_heading_count": 0,
            "omitted_heading_count": 0,
            "truncated": False,
            "ocr_status": "not_enabled",
            "message": self.get_unavailable_message(file_kind),
        }

    async def recognize_to_markdown(self, file_path: str) -> str:
        """预留 OCR 转 Markdown 的统一调用入口。

        后续接入 MinerU 时，在该方法内提交任务、等待解析结果并返回 Markdown；
        调用方无需知道具体 OCR 提供方和部署方式。

        Args:
            file_path: 待 OCR 的原始文件路径。

        Returns:
            OCR 识别后的 Markdown 内容。

        Raises:
            NotImplementedError: 当前版本尚未接入 OCR。
        """
        _ = Path(file_path)
        raise NotImplementedError(self.get_unavailable_message("文件"))
