from fastapi import Request
from fastapi.responses import JSONResponse


class AppError(Exception):
    """Ошибка бизнес-логики: код для программ, текст — для человека."""

    def __init__(self, status: int, code: str, message: str):
        self.status, self.code, self.message = status, code, message


async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(status_code=exc.status, content={"error": {"code": exc.code, "message": exc.message}})


def not_found(what: str = "Объект") -> AppError:
    return AppError(404, "not_found", f"{what} не найден")
