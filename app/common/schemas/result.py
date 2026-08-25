from typing import Generic, Optional, TypeVar

from pydantic import BaseModel


T = TypeVar("T")


class Result(BaseModel, Generic[T]):
    """全局统一响应模型，所有接口都返回 code、msg、data 三个字段。"""

    code: int
    msg: str
    data: Optional[T] = None

    @classmethod
    def success(cls, data: Optional[T] = None, msg: str = "success") -> "Result[T]":
        """
        创建成功响应。

        Args:
            data: 需要返回的数据；没有数据时默认为 None。
            msg: 成功提示信息。
        """
        return cls(code=0, msg=msg, data=data)

    @classmethod
    def fail(cls, code: int, msg: str) -> "Result[None]":
        """
        创建失败响应。

        Args:
            code: 业务错误码或 HTTP 风格错误码。
            msg: 错误说明。
        """
        return cls(code=code, msg=msg, data=None)
