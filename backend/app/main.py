"""FastAPI app: API, webhooks, the built frontend (if present), and the background worker."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager


from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from starlette.middleware.sessions import SessionMiddleware

from . import bootstrap
from .api import public, routes
from .config import REPO_DIR, get_settings
from .workflow import jobs, registry  # noqa: F401

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("rr")

FRONTEND_DIST = REPO_DIR / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = get_settings()
    bootstrap.ensure_dirs()
    bootstrap.migrate()
    bootstrap.seed()
    worker = None
    if cfg.run_worker:
        worker = jobs.Worker()
        worker.start()
    log.info("RequestRunner up (env=%s, email=%s, llm=%s)", cfg.app_env, cfg.email_provider, cfg.llm_provider)
    yield
    if worker:
        worker.stop()


def create_app() -> FastAPI:
    cfg = get_settings()
    app = FastAPI(title="RequestRunner", lifespan=lifespan)
    app.add_middleware(
        SessionMiddleware,
        secret_key=cfg.session_secret,
        same_site="lax",
        https_only=not cfg.is_dev,
        max_age=14 * 24 * 3600,
    )

    @app.middleware("http")
    async def limits_and_headers(request: Request, call_next):
        cl = request.headers.get("content-length")
        if cl and cl.isdigit() and int(cl) > cfg.upload_max_request_bytes:
            return JSONResponse({"detail": "request too large"}, status_code=413)
        resp = await call_next(request)
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "no-referrer")  # upload tokens live in URLs
        resp.headers.setdefault("X-Frame-Options", "DENY")
        return resp

    app.include_router(routes.router)
    app.include_router(public.router)

    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    if FRONTEND_DIST.exists():
        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            f = (FRONTEND_DIST / path).resolve()
            if path and f.is_file() and FRONTEND_DIST in f.parents:
                return FileResponse(f)
            return FileResponse(FRONTEND_DIST / "index.html")

    return app


app = create_app()


