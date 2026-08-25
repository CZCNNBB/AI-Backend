"""知识库模块共享的 MilvusClient 生命周期管理。"""

from threading import RLock

from pymilvus import MilvusClient

from app.server.knowledge.src.config import knowledge_config as settings


class MilvusClientManager:
    """按需创建并复用官方推荐的 MilvusClient。"""

    def __init__(self) -> None:
        """初始化客户端引用和线程锁。"""
        self._client: MilvusClient | None = None
        self._lock = RLock()

    def get_client(self) -> MilvusClient:
        """返回可用客户端；首次调用时完成连接和数据库校验。"""
        with self._lock:
            if self._client is not None:
                return self._client

            client = MilvusClient(
                uri=settings.milvus_uri,
                token=settings.milvus_token,
                db_name=settings.milvus_database,
                timeout=settings.milvus_connect_timeout,
            )
            try:
                databases = client.list_databases(timeout=settings.milvus_connect_timeout)
                if settings.milvus_database not in databases:
                    raise ValueError(
                        f"Milvus database not found: {settings.milvus_database}"
                    )
            except Exception:
                client.close()
                raise

            self._client = client
            return client

    def close(self) -> None:
        """幂等关闭共享客户端，关闭后允许下一次请求重新建立连接。"""
        with self._lock:
            if self._client is None:
                return
            self._client.close()
            self._client = None


# 写入与检索共享同一连接池，避免同一进程重复建立 Milvus 通道。
milvus_client_manager = MilvusClientManager()
