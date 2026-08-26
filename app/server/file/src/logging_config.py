"""文件上传、内容解析与 MinerU 调用共用的日志对象。"""

import logging


# 子模块可继续使用 ai_backend.file.parser、ai_backend.file.ocr 等名称，
# 所有日志最终继承应用统一格式和 LOG_LEVEL。
logger = logging.getLogger("ai_backend.file")
