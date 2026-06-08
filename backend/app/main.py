from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import (
    enterprise,
    evals,
    health,
    hitl,
    kb,
    metrics,
    revisions,
    runs,
    runtime,
    skills,
    stream,
    trace,
    workflows,
)
from app.routes import crawl, knowledge


def create_app() -> FastAPI:
    app = FastAPI(title="Competiscope v2 API", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(runs.router, prefix="/api", tags=["runs"])
    app.include_router(stream.router, prefix="/api", tags=["stream"])
    app.include_router(hitl.router, prefix="/api", tags=["hitl"])
    app.include_router(health.router, prefix="/api", tags=["health"])
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
