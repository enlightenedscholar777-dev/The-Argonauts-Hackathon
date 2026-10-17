import os
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException

from .ai.worker import AIWorker
from .api import error_response, router
from .coordinator import Coordinator
from .errors import DomainError
from .policy import load_policy
from .retrieval import load_procedures
from .settings import Settings
from .storage import Storage


def create_app(settings=None, storage=None, provider=None):
    @asynccontextmanager
    async def lifespan(app):
        config = settings or Settings()
        if int(os.environ.get("WEB_CONCURRENCY", "1")) != 1:
            raise RuntimeError("Harbor demo supports exactly one Uvicorn worker")
        policy = load_policy(config.policy_path)
        procedures = load_procedures(config.procedures_path, policy.procedure_version)
        core = Coordinator(config, policy, storage or Storage(config.database_path), procedures)
        app.state.core = core
        try:
            await core.start()
            core.ai = AIWorker(config, core, provider)
            await core.ai.start()
            yield
        finally:
            if core.ai:
                await core.ai.close()
            await core.stop()

    app = FastAPI(title="Harbor Decision Engine — synthetic demo", version="1.0", lifespan=lifespan)
    # Read only non-secret CORS settings at construction; credentials are validated in lifespan.
    origins = settings.allowed_origins if settings else os.environ.get("ALLOWED_ORIGINS")
    if origins is None:
        from dotenv import dotenv_values

        origins = dotenv_values(".env").get("ALLOWED_ORIGINS", "http://127.0.0.1:8000,http://localhost:8000")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[v.strip() for v in origins.split(",")],
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type"],
    )

    @app.middleware("http")
    async def boundary(request: Request, call_next):
        start = time.perf_counter()
        request.state.request_id = "request_" + uuid.uuid4().hex
        chunks = bytearray()
        async for chunk in request.stream():
            chunks.extend(chunk)
            if len(chunks) > 65536:
                return error_response(
                    DomainError("BODY_TOO_LARGE", "Maximum request body is 64 KiB", 413),
                    request.state.request_id,
                )
        request._body = bytes(chunks)
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'"
        )
        core = getattr(app.state, "core", None)
        if core:
            core.timings["http_ms"].append((time.perf_counter() - start) * 1000)
        return response

    @app.exception_handler(DomainError)
    async def domain_error(request, error):
        return error_response(error, getattr(request.state, "request_id", None))

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, error):
        return error_response(
            DomainError(
                "INVALID_SCHEMA", "Invalid fields, timestamp, or unsupported measurement; see /docs", 422
            ),
            request.state.request_id,
        )

    @app.exception_handler(HTTPException)
    async def http_error(request, error):
        return error_response(
            DomainError("HTTP_ERROR", "Route or method unavailable", error.status_code),
            request.state.request_id,
        )

    @app.exception_handler(Exception)
    async def internal_error(request, error):
        return error_response(
            DomainError("INTERNAL_ERROR", "Request failed; inspect local service health", 503, True),
            getattr(request.state, "request_id", None),
        )

    app.include_router(router)
    app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")
    return app


app = create_app()
