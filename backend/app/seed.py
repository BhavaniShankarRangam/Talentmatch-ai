"""Seed SYNTHETIC demo data.

    python -m app.seed            # tenants, users, sample job, demo files on disk
    python -m app.seed --full     # also approve the mock rubric and ingest + score demo resumes
    python -m app.seed --reset    # wipe the local database and document storage first
"""
import argparse
import json
import shutil
from pathlib import Path

from sqlalchemy import select

from app.config import BACKEND_DIR, get_settings
from app.db import create_schema, drop_schema, new_session
from app.demo.resumes import (
    AI_ENGINEER_JD,
    DATA_SCIENTIST_JD,
    GLOBEX_RESUME,
    MOCK_ATS_RESUMES,
    all_demo_files,
    render,
)
from app.llm.mock import MockLLMProvider
from app.models import IntegrationConfig, JobOpening, Role, Tenant, User
from app.security import hash_password
from app.services import rubric_service as rs
from app.services.pipeline import ingest_document
from app.services.tasks import drain

DEMO_PASSWORD = "TalentMatch-Demo-2026!"
DEMO_DIR = BACKEND_DIR / "demo_data"


def write_demo_files() -> None:
    resumes = DEMO_DIR / "resumes"
    resumes.mkdir(parents=True, exist_ok=True)
    for name, data in all_demo_files().items():
        (resumes / name).write_bytes(data)
    (DEMO_DIR / "jobs").mkdir(exist_ok=True)
    (DEMO_DIR / "jobs" / "ai_engineer_job_description.txt").write_text(AI_ENGINEER_JD, encoding="utf-8")
    ats = DEMO_DIR / "mock_ats"
    (ats / "files").mkdir(parents=True, exist_ok=True)
    for name, fmt, lines in MOCK_ATS_RESUMES.values():
        (ats / "files" / name).write_bytes(render(fmt, lines))
    records = [
        {"external_application_id": "MATS-APP-1001", "external_candidate_id": "MATS-CAND-501",
         "job_external_ref": "REQ-1001", "submitted_at": "2026-09-20T14:05:00Z",
         "resume_file": "mock_ats_quinn_harper.pdf", "simulate_transient_failures": 0},
        {"external_application_id": "MATS-APP-1002", "external_candidate_id": "MATS-CAND-502",
         "job_external_ref": "REQ-1001", "submitted_at": "2026-09-21T09:30:00Z",
         "resume_file": "mock_ats_drew_kim.docx", "simulate_transient_failures": 1},
        {"external_application_id": "MATS-APP-1003", "external_candidate_id": "MATS-CAND-503",
         "job_external_ref": "REQ-1001", "submitted_at": "2026-09-22T16:45:00Z",
         "resume_file": "missing_resume_file.pdf", "simulate_transient_failures": 0},
    ]
    (ats / "applications.json").write_text(json.dumps(records, indent=2), encoding="utf-8")


def _user(db, tenant, email, name, role):
    u = db.scalar(select(User).where(User.email == email))
    if u is None:
        u = User(tenant_id=tenant.id, email=email, full_name=name, role=role, password_hash=hash_password(DEMO_PASSWORD))
        db.add(u)
        db.flush()
    return u


def _tenant(db, slug, name, domains):
    t = db.scalar(select(Tenant).where(Tenant.slug == slug))
    if t is None:
        t = Tenant(slug=slug, name=name, allowed_email_domains=domains, allow_resume_attachments=False,
                   retention_days=365)
        db.add(t)
        db.flush()
    return t


def _job(db, tenant, user, title, ref, jd, department="Engineering", location="Hybrid"):
    j = db.scalar(select(JobOpening).where(JobOpening.tenant_id == tenant.id, JobOpening.external_ref == ref))
    if j is None:
        j = JobOpening(tenant_id=tenant.id, title=title, department=department, location=location,
                       external_ref=ref, created_by_id=user.id)
        db.add(j)
        db.flush()
        rs.add_description_version(db, j, jd, user)
    return j


def seed(full: bool) -> None:
    write_demo_files()
    create_schema()
    db = new_session()
    try:
        acme = _tenant(db, "acme", "Acme Corp (demo)", ["acme.example"])
        admin = _user(db, acme, "admin@acme.example", "Avery Admin", Role.ADMIN)
        recruiter = _user(db, acme, "recruiter@acme.example", "Robin Recruiter", Role.RECRUITER)
        _user(db, acme, "manager@acme.example", "Harper Manager", Role.HIRING_MANAGER)
        if not db.scalar(select(IntegrationConfig).where(IntegrationConfig.tenant_id == acme.id,
                                                         IntegrationConfig.kind == "mock_ats")):
            db.add(IntegrationConfig(tenant_id=acme.id, kind="mock_ats", name="Mock ATS (demo fixtures)",
                                     enabled=True, status="connected_mock", settings={"job_mapping": "external_ref"}))
        ai_job = _job(db, acme, recruiter, "AI Engineer", "REQ-1001", AI_ENGINEER_JD)

        globex = _tenant(db, "globex", "Globex Inc (demo)", ["globex.example"])
        g_admin = _user(db, globex, "admin@globex.example", "Gale Admin", Role.ADMIN)
        _user(db, globex, "recruiter@globex.example", "Glen Recruiter", Role.RECRUITER)
        g_job = _job(db, globex, g_admin, "Data Scientist", "GLX-77", DATA_SCIENTIST_JD)
        db.commit()

        if full:
            provider = MockLLMProvider()
            for job, user in ((ai_job, recruiter), (g_job, g_admin)):
                if not job.active_rubric_version_id:
                    r = rs.propose_rubric(db, job, user, provider)
                    db.flush()
                    rs.approve_rubric(db, r, user)
                    db.commit()
            for name, data in all_demo_files().items():
                ingest_document(db, tenant_id=acme.id, job=ai_job, filename=name, data=data,
                                source_system="manual_upload", user=recruiter)
                db.commit()
            name, fmt, lines = GLOBEX_RESUME
            ingest_document(db, tenant_id=globex.id, job=g_job, filename=name, data=render(fmt, lines),
                            source_system="manual_upload", user=g_admin)
            db.commit()
    finally:
        db.close()
    if full:
        drain(respect_schedule=False)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", action="store_true", help="approve rubric and ingest demo resumes")
    ap.add_argument("--reset", action="store_true", help="wipe local database and stored documents first")
    args = ap.parse_args()
    if args.reset:
        drop_schema()
        storage = Path(get_settings().storage_dir)
        if storage.exists():
            shutil.rmtree(storage)
    seed(args.full)
    print("Seeded SYNTHETIC demo data.")
    print(f"  Sign in: recruiter@acme.example / {DEMO_PASSWORD}  (also admin@, manager@acme.example; admin@globex.example)")
    print(f"  Demo resumes for manual upload: {DEMO_DIR / 'resumes'}")


if __name__ == "__main__":
    main()
