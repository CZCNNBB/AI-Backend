from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from app.common.schemas.result import Result


class BusinessException(Exception):
    """业务异常，用于主动返回统一错误响应。"""

    def __init__(self, code: int = 400, msg: str = "业务处理失败"):
        """
        初始化业务异常。

        Args:
            code: 业务错误码。
            msg: 错误说明。
        """
        self.code = code
        self.msg = msg
        super().__init__(msg)


def register_exception_handlers(app: FastAPI) -> None:
    """
    注册全局异常处理器。

    Args:
        app: FastAPI 应用实例。
    """

    @app.exception_handler(BusinessException)
    async def business_exception_handler(request: Request, error: BusinessException):
        """处理业务主动抛出的异常。"""
        return build_error_response(error.code, error.msg)

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, error: HTTPException):
        """处理 FastAPI/Starlette 抛出的 HTTP 异常。"""
        return build_error_response(error.status_code, str(error.detail))

    @app.exception_handler(RequestValidationError)
    async def request_validation_exception_handler(request: Request, error: RequestValidationError):
        """处理请求参数校验异常。"""
        return build_error_response(422, format_validation_error(error.errors()))

    @app.exception_handler(ValidationError)
    async def pydantic_validation_exception_handler(request: Request, error: ValidationError):
        """处理 Pydantic 数据模型校验异常。"""
        return build_error_response(422, format_validation_error(error.errors()))

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, error: Exception):
        """处理未被业务代码捕获的未知异常。"""
        return build_error_response(500, f"服务内部错误: {str(error)}")


def build_error_response(code: int, msg: str) -> JSONResponse:
    """
    构造统一错误响应。

    Args:
        code: 业务错误码。
        msg: 错误说明。
    """
    # HTTP 状态码统一返回 200，业务是否成功完全由 code 判断，方便 Java 网关统一处理。
    return JSONResponse(status_code=200, content=Result.fail(code, msg).model_dump())


def format_validation_error(errors: list[dict]) -> str:
    """
    把 FastAPI/Pydantic 的校验错误整理成简洁提示。

    Args:
        errors: 校验错误列表。
    """
    if not errors:
        return "请求参数校验失败"

    messages = []
    for item in errors:
        location = ".".join(str(part) for part in item.get("loc", []))
        message = item.get("msg", "参数不合法")
        messages.append(f"{location}: {message}" if location else message)
    return "；".join(messages)
