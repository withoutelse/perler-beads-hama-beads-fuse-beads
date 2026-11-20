from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import __version__
from app.api.deps import get_project_service
from app.api.routes import health, jobs, projects
from app.core.config import settings
from app.core.errors import AppError
from app.core.logging import configure_logging
from app.services.project_service import ProjectService


def create_app(service: ProjectService | None = None) -> FastAPI:
    configure_logging()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        (service or get_project_service()).recover_interrupted_jobs()
        yield

    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        description="Multi-view to 3D Perler bead blueprint pipeline",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(AppError)
    async def handle_app_error(_request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "details": exc.details,
                }
            },
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        _request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        errors = [
            {
                "loc": list(error.get("loc", ())),
                "msg": str(error.get("msg", "invalid value")),
                "type": str(error.get("type", "value_error")),
            }
            for error in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "请求参数校验失败",
                    "details": {"errors": errors},
                }
            },
        )

    app.include_router(health.router)
    app.include_router(projects.router, prefix="/api/v1")
    app.include_router(jobs.router, prefix="/api/v1")
    return app


app = create_app()
