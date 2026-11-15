"""Заголовки безопасности, ID запроса, журнал запросов, лимит размера тела, единый ответ на 500."""
import json
import logging
import secrets
import time

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

log = logging.getLogger("shop.http")
MAX_BODY = 256 * 1024  # самый большой законный запрос — заказ на десятки позиций, это единицы килобайт

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
}
# API отдаёт только JSON: ему не нужны ни скрипты, ни стили. Страница /docs грузит Swagger UI с CDN.
API_CSP = "default-src 'none'; frame-ancestors 'none'"
DOCS_CSP = ("default-src 'none'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "img-src 'self' data: https://fastapi.tiangolo.com; "
            "connect-src 'self'; frame-ancestors 'none'")


class HttpMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        incoming = request.headers.get("x-request-id", "")
        # Чужой ID принимаем, только если он короткий и безопасный — он попадает в журнал
        safe = 0 < len(incoming) <= 64 and incoming.replace("-", "").isascii() and incoming.replace("-", "").isalnum()
        request_id = incoming if safe else secrets.token_hex(8)
        request.state.request_id = request_id
        started = time.perf_counter()

        length = request.headers.get("content-length")
        if length and length.isdigit() and int(length) > MAX_BODY:
            body = {"error": {"code": "payload_too_large", "message": "Слишком большой запрос"}}
            response: Response = JSONResponse(body, status_code=413)
        else:
            try:
                response = await call_next(request)
            except Exception:
                # Подробности — только в журнал; клиент получает код и ID, по которому ошибку можно найти
                log.exception("unhandled error", extra={"request_id": request_id})
                response = JSONResponse({"error": {"code": "internal_error", "message": "Внутренняя ошибка сервера",
                                                   "request_id": request_id}}, status_code=500)

        response.headers["X-Request-ID"] = request_id
        for name, value in SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        docs = request.url.path in ("/docs", "/redoc") or request.url.path.startswith("/docs/")
        response.headers.setdefault("Content-Security-Policy", DOCS_CSP if docs else API_CSP)
        if request.url.path != "/health":  # проверки здоровья раз в несколько секунд засоряли бы журнал
            log.info(json.dumps({
                "request_id": request_id, "method": request.method, "path": request.url.path,
                "status": response.status_code, "ms": round((time.perf_counter() - started) * 1000, 1),
            }))
        return response
