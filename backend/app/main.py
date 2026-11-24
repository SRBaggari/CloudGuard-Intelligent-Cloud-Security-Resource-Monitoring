"""CloudGuard FastAPI application entry point."""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import text

from app.api.routes import (
    analytics, auth, capacity, compliance, containers, dashboard, incidents, integrity, monitoring, notifications, reports, security, settings, topology, users, vms,
    ws,
)
from app.core.config import get_settings
from app.core.database import Base, SessionLocal, engine
from app.core.ratelimit import RateLimitMiddleware
from app.realtime.bus import manager
from app.services.seed import seed

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("cloudguard")


def run_migrations() -> None:
    from pathlib import Path

    from alembic import command
    from alembic.config import Config

    backend = Path(__file__).resolve().parents[1]
    cfg = Config(str(backend / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend / "alembic"))
    cfg.set_main_option("sqlalchemy.url", get_settings().database_url.replace("%", "%%"))
    command.upgrade(cfg, "head")


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    if s.app_env == "test":
        Base.metadata.create_all(engine)
    elif s.auto_migrate:
        await asyncio.to_thread(run_migrations)
    with SessionLocal() as db:
        seed(db)
    manager.bind_loop(asyncio.get_running_loop())
    tasks = []
    if s.enable_background_tasks:
        from app.services.scheduler import start_background_tasks
        tasks = start_background_tasks()
        log.info("CloudGuard started (integration mode: %s, db: %s)", s.integration_mode,
                 "sqlite" if s.is_sqlite else "postgresql")
    yield
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    from app.monitoring.collector import collector
    collector.shutdown()


settings_ = get_settings()
app = FastAPI(
    title="CloudGuard API",
    description="Intelligent Cloud Security & Resource Monitoring System. Authenticate via **/api/auth/login** and "
                "use the access token as a Bearer token.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(RateLimitMiddleware, auth_limit=settings_.rate_limit_auth_per_minute,
                   default_limit=settings_.rate_limit_default_per_minute)
app.add_middleware(
    CORSMiddleware, allow_origins=settings_.cors_origin_list, allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"], allow_headers=["Authorization", "Content-Type"],
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    if request.url.path.startswith("/api/"):
        response.headers.setdefault("Cache-Control", "no-store")
    return response


@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError):
    errors = [{"field": ".".join(str(p) for p in e["loc"] if p != "body"), "message": e["msg"]} for e in exc.errors()]
    return JSONResponse(status_code=422, content={"detail": "Validation failed", "errors": errors})


@app.exception_handler(Exception)
async def unhandled_handler(request: Request, exc: Exception):
    if isinstance(exc, HTTPException):
        raise exc
    log.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


for r in (auth, users, dashboard, monitoring, containers, vms, security, integrity, analytics, reports, settings,
          notifications, incidents, topology, compliance, capacity, ws):
    app.include_router(r.router)


@app.get("/api/health", tags=["System"])
def api_health():
    """Unauthenticated liveness probe (no sensitive information)."""
    try:
        with engine.connect() as c:
            c.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False
    return {"status": "ok" if db_ok else "degraded", "database": db_ok, "version": app.version}


@app.get("/metrics", include_in_schema=False)
def prometheus_metrics(request: Request):
    s = get_settings()
    if not s.prometheus_enabled:
        return JSONResponse({"detail": "Not found"}, status_code=404)
    if s.prometheus_token and request.headers.get("authorization") != f"Bearer {s.prometheus_token}":
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
