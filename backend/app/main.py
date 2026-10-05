import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from app.core.config import settings
from app.core.logging import logger
from app.db.session import init_db, SessionLocal
from app.db.seed_data import seed_database
from app.db.guards import ensure_triggers
from app.core.errors import register_error_handlers
from app.api import (
    auth, requests, verification, agent, inventory,
    approvals, actions, export, audit, fulfilment, policy, system
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize DB tables
    init_db()
    db = SessionLocal()
    try:
        ensure_triggers(db)
        if settings.SEED_ON_START:
            seed_database(db)
    finally:
        db.close()
    logger.info("Application startup complete", env=settings.APP_ENV)
    yield

app = FastAPI(
    title="Data Privacy Request Fulfilment Workbench",
    description="Internal privacy request management aid conforming to Acme Privacy Request Handling Policy v1.0.",
    version="1.0.0",
    lifespan=lifespan
)

# CORS locked to configured origins (NFR-1); the SPA is served same-origin in production.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Correlation-ID"],
)


@app.middleware("http")
async def correlation_middleware(request: Request, call_next):
    cid = request.headers.get("x-correlation-id") or f"corr-{uuid.uuid4().hex[:10]}"
    request.state.correlation_id = cid
    start = time.time()
    response = await call_next(request)
    response.headers["X-Correlation-ID"] = cid
    if request.url.path.startswith("/api"):
        logger.info("http_request", component="api", method=request.method, path=request.url.path,
                    status=response.status_code, duration_ms=round((time.time() - start) * 1000, 1), correlation_id=cid)
    return response


register_error_handlers(app)

# Include API Routers under /api
api_prefix = "/api"
app.include_router(auth.router, prefix=api_prefix)
app.include_router(requests.router, prefix=api_prefix)
app.include_router(verification.router, prefix=api_prefix)
app.include_router(agent.router, prefix=api_prefix)
app.include_router(inventory.router, prefix=api_prefix)
app.include_router(approvals.router, prefix=api_prefix)
app.include_router(actions.router, prefix=api_prefix)
app.include_router(export.router, prefix=api_prefix)
app.include_router(audit.router, prefix=api_prefix)
app.include_router(fulfilment.router, prefix=api_prefix)
app.include_router(policy.router, prefix=api_prefix)
app.include_router(system.router, prefix=api_prefix)

# Public health endpoint
@app.get("/api/health")
@app.get("/health")
def root_health():
    return {"status": "ok", "app": "Privacy Workbench", "version": "1.1.0"}

# Serve frontend static build if exists
FRONTEND_DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        if full_path.startswith("api/"):
            return JSONResponse(status_code=404, content={"error": {"code": "NOT_FOUND", "message": "Unknown API route", "rule_ids": [], "correlation_id": "n/a"}, "detail": "Unknown API route"})
        file_path = (FRONTEND_DIST / full_path).resolve()
        if FRONTEND_DIST.resolve() not in file_path.parents and file_path != FRONTEND_DIST.resolve():
            return FileResponse(FRONTEND_DIST / "index.html")
        if file_path.is_file():
            return FileResponse(file_path)
        return FileResponse(FRONTEND_DIST / "index.html")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=settings.PORT, reload=True)
