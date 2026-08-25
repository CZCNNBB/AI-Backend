"""知识文档入库执行服务兼容入口。"""

from app.server.knowledge.src.ingestion.executor import IngestionExecutor, ingestion_executor

# 对外仍保留 ingestion_service 名称，实际执行逻辑集中在 IngestionExecutor。
ingestion_service = ingestion_executor

__all__ = ["IngestionExecutor", "ingestion_executor", "ingestion_service"]
