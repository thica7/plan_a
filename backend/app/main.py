import os

from fastapi import FastAPI
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.middleware.auth import AuthMiddleware
from app.middleware.redis_rate_limit import RedisRateLimitMiddleware
from app.routers import (
    enterprise,
    evals,
    health,
    hitl,
    kb,
    metrics,
    readiness,
    revisions,
    runs,
    runtime,
    skills,
    stream,
    task_submissions,
    trace,
    workflows,
)
from app.routes import crawl, knowledge
from packages.infrastructure.execution_control import ExecutionControlError

_CORS_ORIGINS = os.getenv("CORS_ORIGINS", "*").split(",")


def create_app() -> FastAPI:
    from packages.config.settings import validate_env_vars

    app = FastAPI(title="Competiscope v2 API", version="0.1.0")

    from packages.task_center.errors import TaskCenterError

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        path = request.url.path
        if path.startswith("/api/task-submissions") or (
            path.startswith("/api/workspaces/") and path.endswith("/quota-ledger")
        ):
            return JSONResponse(status_code=422, content={
                "detail": "Invalid task center request", "code": "invalid_task_center_request",
                "errors": [{"loc": list(error["loc"]), "type": error["type"]}
                           for error in exc.errors()],
            })
        return await request_validation_exception_handler(request, exc)

    @app.exception_handler(TaskCenterError)
    async def task_center_error(request, exc):
        code = getattr(exc, "status_code", 503)
        return JSONResponse(status_code=code, content={"detail": str(exc), "code": exc.code},
                            headers={"Retry-After": "1"} if code == 503 else None)

    @app.exception_handler(ExecutionControlError)
    async def execution_control_error(request, exc):
        return JSONResponse(
            status_code=exc.status_code, content={"detail": str(exc)},
            headers={"Retry-After": str(exc.retry_after_seconds)},
        )

    @app.on_event("startup")
    async def startup_event():
        validate_env_vars()
        from app import deps
        settings = deps.get_app_settings()
        if settings.task_center_enabled:
            import asyncio

            from packages.task_center.factory import get_task_service
            store = await asyncio.to_thread(deps.get_enterprise_store)
            journal = await asyncio.to_thread(deps.get_run_journal)
            service = get_task_service(settings, store=store, journal=journal)
            await service.open()

    async def shutdown_event():
        import asyncio

        from app import deps
        from packages.infrastructure.redis_config import get_redis_runtime
        from packages.task_center.factory import close_task_services, stop_task_services
        await stop_task_services()
        await deps.close_run_services()
        await close_task_services()
        if deps.get_enterprise_store.cache_info().currsize:
            store = deps.get_enterprise_store()
            if hasattr(store, "close"):
                await asyncio.to_thread(store.close)
            deps.get_enterprise_store.cache_clear()

        if get_redis_runtime.cache_info().currsize:
            await get_redis_runtime().aclose()
            get_redis_runtime.cache_clear()

    app.router.add_event_handler("shutdown", shutdown_event)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=_CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(RedisRateLimitMiddleware)
    app.add_middleware(AuthMiddleware)
    app.include_router(task_submissions.router, prefix="/api", tags=["task-submissions"])
    app.include_router(runs.router, prefix="/api", tags=["runs"])
    app.include_router(stream.router, prefix="/api", tags=["stream"])
    app.include_router(hitl.router, prefix="/api", tags=["hitl"])
    app.include_router(health.router, prefix="/api", tags=["health"])
    app.include_router(readiness.router, prefix="/api", tags=["health"])
    app.include_router(metrics.router, prefix="/api", tags=["metrics"])
    app.include_router(skills.router, prefix="/api", tags=["skills"])
    app.include_router(runtime.router, prefix="/api", tags=["runtime"])
    app.include_router(trace.router, prefix="/api", tags=["trace"])
    app.include_router(knowledge.router, prefix="/api", tags=["knowledge"])
    app.include_router(crawl.router, prefix="/api", tags=["crawl"])
    app.include_router(kb.router, prefix="/api", tags=["kb"])
    app.include_router(revisions.router, prefix="/api", tags=["revisions"])
    app.include_router(enterprise.router, prefix="/api", tags=["enterprise"])
    app.include_router(evals.router, prefix="/api", tags=["evals"])
    app.include_router(workflows.router, prefix="/api", tags=["workflows"])
    return app


app = create_app()
