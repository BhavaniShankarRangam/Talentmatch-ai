from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import audit
from app.config import get_settings
from app.db import get_db
from app.deps import require
from app.deps import get_scoped_or_404
from app.files import UploadRejected
from app.ingestion.email_intake import ingest_email
from app.models import AuditLog, IngestedMessage, IntegrationConfig, JobOpening, Tenant, User
from app.services.ingestion_tasks import IMAP_KIND
from app.services.tasks import enqueue
from app.services.chat_service import handle_message
from app.services.ingestion_tasks import start_sync
from app.services.retention import run_retention

router = APIRouter(prefix="/api", tags=["integrations, settings, audit, chat"])

# Static catalogue: what exists, and its honest status.
INTEGRATION_CATALOG = [
    {"kind": "manual_upload", "name": "Manual upload (PDF/DOCX)", "implemented": True, "is_mock": False},
    {"kind": "mock_ats", "name": "Mock ATS connector (demo fixtures)", "implemented": True, "is_mock": True},
    {"kind": "mock_email", "name": "Mock email outbox", "implemented": True, "is_mock": True},
    {"kind": "csv_import", "name": "CSV import of application records", "implemented": False, "is_mock": False},
    {"kind": "mailbox_eml", "name": "Recruitment mailbox: .eml import", "implemented": True, "is_mock": False,
     "needs": "Export application emails from the recruitment inbox as .eml and import them here."},
    {"kind": "imap_mailbox", "name": "Recruitment mailbox: read-only IMAP sync", "implemented": True, "is_mock": False,
     "needs": "Implemented but NOT yet tested against a real mailbox. Needs mailbox owner authorization, "
              "IMAP enabled, and MAILBOX_IMAP_PASSWORD (app password) set on the server. OAuth 2.0 not implemented."},
    {"kind": "ats", "name": "Applicant tracking system", "implemented": False, "is_mock": False,
     "needs": "Which ATS and API edition? Webhooks or polling? Sandbox credentials?"},
    {"kind": "email_provider", "name": "Production email provider", "implemented": False, "is_mock": False,
     "needs": "Which provider (Microsoft Graph, SES, SendGrid, SMTP relay) and sender identity?"},
    {"kind": "llm_provider", "name": "LLM provider", "implemented": False, "is_mock": False,
     "needs": "Which approved LLM service and data-processing terms?"},
]


def _dt(d):
    return d.isoformat() + "Z" if d else None


@router.get("/integrations")
def list_integrations(user: User = Depends(require("integrations:read")), db: Session = Depends(get_db)):
    cfgs = {c.kind: c for c in db.scalars(select(IntegrationConfig).where(IntegrationConfig.tenant_id == user.tenant_id))}
    s = get_settings()
    out = []
    for item in INTEGRATION_CATALOG:
        c = cfgs.get(item["kind"])
        out.append({**item, "enabled": bool(c.enabled) if c else item["kind"] in ("manual_upload",),
                    "status": c.status if c else ("available" if item["implemented"] else "not_implemented"),
                    "last_sync_at": _dt(c.last_sync_at) if c else None, "last_result": c.last_result if c else {}})
    return {"integrations": out, "runtime": {"llm_provider": s.llm_provider, "email_provider": s.email_provider,
                                             "demo_mode": s.demo_mode, "task_mode": s.task_mode}}


@router.post("/integrations/mock-ats/sync")
def sync_mock_ats(user: User = Depends(require("integrations:sync")), db: Session = Depends(get_db)):
    cfg = db.scalar(select(IntegrationConfig).where(IntegrationConfig.tenant_id == user.tenant_id,
                                                    IntegrationConfig.kind == "mock_ats"))
    if cfg is None or not cfg.enabled:
        raise HTTPException(409, "The mock ATS connector is not enabled for this organization.")
    result = start_sync(db, user, "mock_ats")
    db.commit()
    return result


def _message_out(m: IngestedMessage) -> dict:
    return {"id": m.id, "source": m.source, "sender_email": m.sender_email, "subject": m.subject,
            "received_at": _dt(m.received_at), "outcome": m.outcome, "detail": m.detail, "job_id": m.job_id,
            "application_ids": m.application_ids, "created_at": _dt(m.created_at)}


@router.post("/integrations/mailbox/import-eml")
async def import_eml(files: list[UploadFile] = File(...), job_id: str | None = Form(None),
                     user: User = Depends(require("applications:upload")), db: Session = Depends(get_db)):
    """Import application emails exported (.eml) from the recruitment inbox."""
    if len(files) > 100:
        raise HTTPException(400, "Import at most 100 emails at a time.")
    job = get_scoped_or_404(db, JobOpening, job_id, user.tenant_id) if job_id else None
    limit = get_settings().max_email_mb * 1024 * 1024
    out = []
    for f in files:
        if not (f.filename or "").lower().endswith(".eml"):
            out.append({"filename": f.filename, "outcome": "rejected_message", "detail": "Not an .eml file."})
            continue
        raw = await f.read(limit + 1)
        try:
            rec = ingest_email(db, tenant_id=user.tenant_id, raw=raw, source="mailbox_eml", user=user, job_override=job)
            db.commit()
            out.append({"filename": f.filename, **_message_out(rec)})
        except UploadRejected as e:
            db.rollback()
            out.append({"filename": f.filename, "outcome": "rejected_message", "detail": str(e)})
    return {"results": out}


@router.get("/integrations/mailbox/messages")
def mailbox_messages(user: User = Depends(require("integrations:read")), db: Session = Depends(get_db)):
    rows = db.scalars(select(IngestedMessage).where(IngestedMessage.tenant_id == user.tenant_id)
                      .order_by(IngestedMessage.created_at.desc()).limit(200)).all()
    return [_message_out(m) for m in rows]


class ImapConfigIn(BaseModel):
    enabled: bool
    host: str = Field(min_length=3, max_length=200, pattern=r"^[A-Za-z0-9.-]+$")
    port: int = Field(default=993, ge=1, le=65535)
    username: str = Field(min_length=3, max_length=320)
    # No quotes, backslashes or line breaks: the folder name goes inside an IMAP quoted string.
    folder: str = Field(default="INBOX", max_length=200, pattern=r'^[^"\\\r\n]+$')
    since_days: int = Field(default=30, ge=1, le=365)


def _imap_out(c: IntegrationConfig | None) -> dict:
    return {"configured": c is not None, "enabled": bool(c and c.enabled), "status": c.status if c else "not_configured",
            "settings": (c.settings if c else {}), "last_sync_at": _dt(c.last_sync_at) if c else None,
            "last_result": c.last_result if c else {},
            "password_configured_on_server": bool(get_settings().mailbox_imap_password),
            "tested_against_real_mailbox": False}


@router.get("/integrations/imap")
def get_imap(user: User = Depends(require("integrations:read")), db: Session = Depends(get_db)):
    return _imap_out(db.scalar(select(IntegrationConfig).where(IntegrationConfig.tenant_id == user.tenant_id,
                                                               IntegrationConfig.kind == IMAP_KIND)))


@router.put("/integrations/imap")
def put_imap(body: ImapConfigIn, user: User = Depends(require("settings:write")), db: Session = Depends(get_db)):
    c = db.scalar(select(IntegrationConfig).where(IntegrationConfig.tenant_id == user.tenant_id,
                                                  IntegrationConfig.kind == IMAP_KIND))
    if c is None:
        c = IntegrationConfig(tenant_id=user.tenant_id, kind=IMAP_KIND, name="Recruitment mailbox (IMAP, read-only)")
        db.add(c)
    c.enabled = body.enabled
    c.settings = body.model_dump(exclude={"enabled"})
    c.status = "configured" if body.enabled else "disabled"
    audit.record(db, tenant_id=user.tenant_id, user=user, action="integration.imap_configured", entity_type="integration",
                 entity_id=IMAP_KIND, details={**c.settings, "enabled": c.enabled})
    db.commit()
    return _imap_out(c)


@router.post("/integrations/imap/sync")
def sync_imap(user: User = Depends(require("integrations:sync")), db: Session = Depends(get_db)):
    c = db.scalar(select(IntegrationConfig).where(IntegrationConfig.tenant_id == user.tenant_id,
                                                  IntegrationConfig.kind == IMAP_KIND))
    if c is None or not c.enabled:
        raise HTTPException(409, "The IMAP mailbox integration is not configured and enabled.")
    if not get_settings().mailbox_imap_password:
        raise HTTPException(409, "MAILBOX_IMAP_PASSWORD is not set on the server.")
    enqueue(db, user.tenant_id, "imap_sync", {"kind": IMAP_KIND}, max_attempts=3)
    c.status = "sync_requested"
    audit.record(db, tenant_id=user.tenant_id, user=user, action="integration.sync_started", entity_type="integration",
                 entity_id=IMAP_KIND)
    db.commit()
    return {"queued": True}


class TenantSettingsIn(BaseModel):
    allowed_email_domains: list[str] | None = None
    allow_resume_attachments: bool | None = None
    retention_days: int | None = Field(default=None, ge=30, le=3650)


def tenant_out(t: Tenant) -> dict:
    return {"id": t.id, "name": t.name, "slug": t.slug, "allowed_email_domains": t.allowed_email_domains,
            "allow_resume_attachments": t.allow_resume_attachments, "retention_days": t.retention_days}


@router.get("/settings/tenant")
def get_tenant_settings(user: User = Depends(require("integrations:read")), db: Session = Depends(get_db)):
    return tenant_out(db.get(Tenant, user.tenant_id))


@router.put("/settings/tenant")
def put_tenant_settings(body: TenantSettingsIn, user: User = Depends(require("settings:write")),
                        db: Session = Depends(get_db)):
    t = db.get(Tenant, user.tenant_id)
    changes = body.model_dump(exclude_unset=True)
    if "allowed_email_domains" in changes:
        doms = [d.strip().lower().lstrip("@") for d in changes["allowed_email_domains"] if d.strip()]
        if any("." not in d or " " in d for d in doms):
            raise HTTPException(422, "Domains must look like example.com")
        changes["allowed_email_domains"] = doms
    for k, v in changes.items():
        setattr(t, k, v)
    audit.record(db, tenant_id=t.id, user=user, action="settings.updated", entity_type="tenant", entity_id=t.id,
                 details=changes)
    db.commit()
    return tenant_out(t)


@router.post("/admin/retention/run")
def retention(user: User = Depends(require("data:delete")), db: Session = Depends(get_db)):
    n = run_retention(db, db.get(Tenant, user.tenant_id), user)
    db.commit()
    return {"deleted_applications": n}


@router.get("/audit")
def audit_log(page: int = 1, page_size: int = 50, action: str | None = None,
              user: User = Depends(require("audit:read")), db: Session = Depends(get_db)):
    page_size = max(1, min(page_size, 200))
    q = select(AuditLog).where(AuditLog.tenant_id == user.tenant_id)
    if action:
        q = q.where(AuditLog.action.like(f"{action}%"))
    total = db.scalar(select(func.count()).select_from(q.subquery()))
    rows = db.scalars(q.order_by(AuditLog.created_at.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    return {"total": total, "page": page, "items": [
        {"id": r.id, "created_at": _dt(r.created_at), "actor_email": r.actor_email, "action": r.action,
         "entity_type": r.entity_type, "entity_id": r.entity_id, "details": r.details} for r in rows]}


class ChatIn(BaseModel):
    message: str = Field(max_length=2000)
    context: dict = {}


@router.post("/chat")
def chat(body: ChatIn, user: User = Depends(require("chat:use")), db: Session = Depends(get_db)):
    out = handle_message(db, user, body.message, body.context or {})
    db.commit()
    return out
