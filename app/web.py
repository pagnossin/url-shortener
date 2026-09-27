import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, Field
from pymongo.errors import PyMongoError

from .bootstrap import build_service, create_mongo_client
from .config import Settings
from .errors import (
    InvalidShortUrlError,
    InvalidUrlError,
    ShortenerError,
    ShortUrlExpiredError,
    ShortUrlNotFoundError,
)
from .observability import RequestContextMiddleware, configure_logging
from .repository import ShortUrl
from .service import UrlShortenerService

log = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"
MAX_REDIRECT_CACHE_SECONDS = 3600
PAGE_CSP = "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'"

STATUS_BY_ERROR: dict[type[ShortenerError], int] = {
    InvalidUrlError: 400,
    InvalidShortUrlError: 400,
    ShortUrlNotFoundError: 404,
    ShortUrlExpiredError: 410,
}


class MinifyRequest(BaseModel):
    url: str = Field(max_length=4096)


class ShortUrlResponse(BaseModel):
    short_url: str
    code: str
    long_url: str
    created_at: datetime
    expires_at: datetime
    created: bool = False


def create_app(service_factory: Callable[[], UrlShortenerService] | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if service_factory is not None:
            app.state.service = service_factory()
            app.state.ping = lambda: None
            yield
            return

        configure_logging()
        settings = Settings.from_env()
        client = create_mongo_client(settings)
        app.state.service = build_service(settings, client, with_cache=True)
        app.state.ping = lambda: client.admin.command("ping")
        log.info("started", extra={"fields": {"base_url": settings.base_url}})
        yield
        client.close()

    app = FastAPI(title="URL Shortener", version="1.0.0", lifespan=lifespan)
    app.add_middleware(RequestContextMiddleware)

    def service(request: Request) -> UrlShortenerService:
        svc: UrlShortenerService = request.app.state.service
        return svc

    @app.exception_handler(ShortenerError)
    async def domain_error(_: Request, exc: ShortenerError) -> JSONResponse:
        status = STATUS_BY_ERROR.get(type(exc), 503)
        headers = {"Cache-Control": "no-store"}
        if isinstance(exc, ShortUrlExpiredError):
            headers["Cache-Control"] = "public, max-age=3600"
        if status == 503:
            headers["Retry-After"] = "2"
        return JSONResponse(status_code=status, content=_error(exc), headers=headers)

    @app.exception_handler(PyMongoError)
    async def storage_error(request: Request, exc: PyMongoError) -> JSONResponse:
        log.warning(
            "storage error",
            extra={"fields": {"error": type(exc).__name__, "request_id": getattr(request.state, "request_id", None)}},
        )
        return JSONResponse(
            status_code=503,
            content={"error": "StorageUnavailable", "detail": "Temporarily unavailable, retry shortly"},
            headers={"Retry-After": "2", "Cache-Control": "no-store"},
        )

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html", headers={"Content-Security-Policy": PAGE_CSP})

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        # liveness only, deliberately not tied to mongo (that's /readyz)
        return {"status": "ok"}

    @app.get("/readyz")
    def readyz(request: Request) -> JSONResponse:
        try:
            request.app.state.ping()
        except PyMongoError as exc:
            return JSONResponse(status_code=503, content={"status": "unavailable", "mongo": type(exc).__name__})
        return JSONResponse(content={"status": "ready"})

    @app.post("/api/minify", response_model=ShortUrlResponse)
    def minify(body: MinifyRequest, request: Request) -> JSONResponse:
        result = service(request).minify(body.url)
        payload = _to_response(result.short_url, result.record, created=result.created)
        return JSONResponse(
            status_code=201 if result.created else 200,
            content=payload.model_dump(mode="json"),
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/api/expand", response_model=ShortUrlResponse)
    def expand(short_url: str, request: Request, response: Response) -> ShortUrlResponse:
        svc = service(request)
        record = svc.expand(short_url)
        response.headers["Cache-Control"] = "no-store"
        return _to_response(svc.short_url_for(record.code), record)

    @app.get("/{code}", include_in_schema=False)
    def redirect(code: str, request: Request) -> RedirectResponse:
        svc = service(request)
        record = svc.resolve_code(code)
        # 307 and a bounded max-age: a 301 would be cached by browsers after the link expires
        max_age = min(svc.seconds_to_expiry(record), MAX_REDIRECT_CACHE_SECONDS)
        return RedirectResponse(
            record.long_url, status_code=307, headers={"Cache-Control": f"public, max-age={max_age}"}
        )

    return app


def _error(exc: ShortenerError) -> dict[str, str]:
    return {"error": type(exc).__name__, "detail": str(exc)}


def _to_response(short_url: str, record: ShortUrl, created: bool = False) -> ShortUrlResponse:
    return ShortUrlResponse(
        short_url=short_url,
        code=record.code,
        long_url=record.long_url,
        created_at=record.created_at,
        expires_at=record.expires_at,
        created=created,
    )


app = create_app()
