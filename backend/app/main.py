import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import DEV_JWT_SECRET, get_settings
from app.db import create_schema
from app.routers import admin, applications, auth, jobs, shortlist
from app.services.tasks import WorkerThread

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("talentmatch")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    s = get_settings()
    if s.jwt_secret == DEV_JWT_SECRET and s.app_env != "development":
        raise RuntimeError("JWT_SECRET must be set outside development.")
    create_schema()
    worker = None
    if s.task_mode == "thread":
        worker = WorkerThread()
        worker.start()
        log.info("in-process background worker started")
    log.info("TalentMatch AI API ready (llm=%s, email=%s, demo_mode=%s)", s.llm_provider, s.email_provider, s.demo_mode)
    yield
    if worker:
        worker.stop()


app = FastAPI(
    title="TalentMatch AI API",
    version="0.1.0-milestone1",
    description="Recruitment assistant API. Demo mode uses MOCK extraction/scoring and a MOCK email outbox.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in get_settings().cors_origins.split(",") if o.strip()],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
)
for r in (auth.router, jobs.router, applications.router, shortlist.router, admin.router):
    app.include_router(r)


@app.get("/api/health", tags=["health"])
def health():
    s = get_settings()
    return {"status": "ok", "demo_mode": s.demo_mode, "llm_provider": s.llm_provider,
            "email_provider": s.email_provider, "mock_services": s.llm_provider == "mock" or s.email_provider == "mock"}
