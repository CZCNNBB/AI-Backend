"""Retrieval 服务可预期异常定义。"""


class RetrievalError(Exception):
    """Retrieval 可预期异常基类。"""


class RetrievalValidationError(RetrievalError):
    """请求参数或外部结果不满足检索约束。"""


class RetrievalNotFoundError(RetrievalError):
    """目标 Milvus collection 不存在。"""


class RetrievalDependencyError(RetrievalError):
    """Embedding 或 Milvus 外部依赖调用失败。"""
