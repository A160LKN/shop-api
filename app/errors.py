from fastapi import Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import TimeoutError as PoolTimeout


class AppError(Exception):
    """Ошибка бизнес-логики: код для программ, текст — для человека."""

    def __init__(self, status: int, code: str, message: str):
        self.status, self.code, self.message = status, code, message


async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(status_code=exc.status, content={"error": {"code": exc.code, "message": exc.message}})


async def overload_handler(_: Request, __: PoolTimeout) -> JSONResponse:
    """Все соединения с БД заняты: честный 503 с подсказкой, когда повторить, вместо 500."""
    return JSONResponse(status_code=503, headers={"Retry-After": "5"},
                        content={"error": {"code": "overloaded",
                                           "message": "Сервис перегружен — повторите запрос через несколько секунд"}})


def not_found(what: str = "Объект") -> AppError:
    return AppError(404, "not_found", f"{what} не найден")
