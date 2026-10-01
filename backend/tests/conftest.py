import os
import tempfile
import uuid
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="talentmatch-tests-"))
os.environ.update({
    "DATABASE_URL": f"sqlite:///{(_TMP / 'test.db').as_posix()}",
    "STORAGE_DIR": str(_TMP / "documents"),
    "TASK_MODE": "inline",
    "LLM_PROVIDER": "mock",
    "EMAIL_PROVIDER": "mock",
    "APP_ENV": "test-development",
    "JWT_SECRET": "test-secret-not-for-production-0123456789",
    "TASK_RETRY_BASE_SECONDS": "0",
})

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.config import get_settings  # noqa: E402

get_settings.cache_clear()

from app.db import create_schema, drop_schema, init_engine  # noqa: E402
from app.demo.resumes import AI_ENGINEER_JD, RESUMES, render  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Role, Tenant, User  # noqa: E402
from app.db import new_session  # noqa: E402
from app.security import hash_password  # noqa: E402
from app.services.tasks import drain  # noqa: E402

PASSWORD = "pw-123456"


@pytest.fixture(autouse=True)
def fresh_db():
    init_engine()
    drop_schema()
    create_schema()
    yield


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def make_tenant(slug: str, domains=None, attachments=False) -> dict:
    db = new_session()
    t = Tenant(slug=slug, name=slug.title(), allowed_email_domains=domains or [f"{slug}.example"],
               allow_resume_attachments=attachments)
    db.add(t)
    db.flush()
    users = {}
    for role in Role.ALL:
        u = User(tenant_id=t.id, email=f"{role}@{slug}.example", full_name=f"{role} {slug}", role=role,
                 password_hash=hash_password(PASSWORD))
        db.add(u)
        users[role] = u.email
    db.commit()
    tid = t.id
    db.close()
    return {"tenant_id": tid, "users": users}


def login(client, email) -> dict:
    r = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
def acme(client):
    t = make_tenant("acme")
    t["recruiter"] = login(client, t["users"]["recruiter"])
    t["admin"] = login(client, t["users"]["admin"])
    t["manager"] = login(client, t["users"]["hiring_manager"])
    return t


@pytest.fixture
def globex(client):
    t = make_tenant("globex")
    t["recruiter"] = login(client, t["users"]["recruiter"])
    return t


def create_job(client, headers, jd=AI_ENGINEER_JD, title="AI Engineer") -> str:
    r = client.post("/api/jobs", json={"title": title, "description": jd, "external_ref": "REQ-1001"}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def propose_and_approve(client, headers, job_id) -> dict:
    r = client.post(f"/api/jobs/{job_id}/rubrics/propose", headers=headers)
    assert r.status_code == 201, r.text
    rid = r.json()["id"]
    r = client.post(f"/api/rubrics/{rid}/approve", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["rubric"]


def upload(client, headers, job_id, files: dict[str, bytes]) -> list[dict]:
    payload = [("files", (name, data, "application/octet-stream")) for name, data in files.items()]
    r = client.post(f"/api/jobs/{job_id}/applications/upload", files=payload, headers=headers)
    assert r.status_code == 200, r.text
    drain(respect_schedule=False)
    return r.json()["results"]


def resume(key: str) -> tuple[str, bytes]:
    name, fmt, lines = RESUMES[key]
    return name, render(fmt, lines)


@pytest.fixture
def scored_job(client, acme):
    """AI Engineer job with approved mock rubric and all scenario resumes processed."""
    job_id = create_job(client, acme["recruiter"])
    propose_and_approve(client, acme["recruiter"], job_id)
    files = dict(resume(k) for k in ("strong", "near_boundary", "just_below", "missing_required", "partial", "injection"))
    results = upload(client, acme["recruiter"], job_id, files)
    ids = {r["filename"]: r["application_id"] for r in results}
    return {"job_id": job_id, "ids": ids, **acme}


def new_key() -> str:
    return uuid.uuid4().hex
