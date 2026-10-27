from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit
from app.db import get_db
from app.deps import require
from app.models import EmailSend, MockOutboxMessage, User
from app.services.email_service import ShortlistRequest, build_preview, request_send

router = APIRouter(prefix="/api", tags=["shortlist & email"])


class ShortlistIn(BaseModel):
    job_id: str
    application_ids: list[str]
    to: str | list[str]
    cc: str | list[str] | None = None
    subject: str = Field(max_length=300)
    message: str = Field(max_length=20_000)
    include_attachments: bool = False
    score_min: float | None = None
    score_max: float | None = None
    confirm_external_recipients: bool = False


def _dt(d):
    return d.isoformat() + "Z" if d else None


def send_out(s: EmailSend) -> dict:
    return {
        "id": s.id, "job_id": s.job_id, "sender_email": s.sender_email, "to": s.to_recipients, "cc": s.cc_recipients,
        "external_recipients": s.external_recipients, "subject": s.subject, "application_ids": s.application_ids,
        "score_min": s.score_min, "score_max": s.score_max, "include_attachments": s.include_attachments,
        "status": s.status, "delivery_status": s.delivery_status, "provider": s.provider,
        "provider_message_id": s.provider_message_id, "failure_detail": s.failure_detail,
        "created_at": _dt(s.created_at), "accepted_at": _dt(s.accepted_at),
        "status_note": ("Accepted by the MOCK provider (written to the demo outbox). Delivery is not confirmed."
                        if s.status == "accepted" and s.provider == "mock_outbox" else
                        "Accepted by provider; delivery not yet confirmed." if s.status == "accepted" else None),
    }


@router.post("/shortlists/preview")
def preview(body: ShortlistIn, user: User = Depends(require("shortlist:send")), db: Session = Depends(get_db)):
    p = build_preview(db, user, ShortlistRequest(**body.model_dump()))
    audit.record(db, tenant_id=user.tenant_id, user=user, action="shortlist.previewed", entity_type="job",
                 entity_id=body.job_id, details={"candidate_count": p["candidate_count"], "valid": p["valid"]})
    db.commit()
    return p


@router.post("/shortlists/send")
def send(body: ShortlistIn, idempotency_key: str = Header(..., alias="Idempotency-Key"),
         user: User = Depends(require("shortlist:send")), db: Session = Depends(get_db)):
    s, created = request_send(db, user, ShortlistRequest(**body.model_dump()), idempotency_key)
    return {"send": send_out(s), "duplicate_request": not created}


@router.get("/shortlists/sends")
def list_sends(user: User = Depends(require("shortlist:send")), db: Session = Depends(get_db)):
    rows = db.scalars(select(EmailSend).where(EmailSend.tenant_id == user.tenant_id)
                      .order_by(EmailSend.created_at.desc()).limit(100)).all()
    return [send_out(s) for s in rows]


@router.get("/shortlists/sends/{send_id}")
def get_send(send_id: str, user: User = Depends(require("shortlist:send")), db: Session = Depends(get_db)):
    from app.deps import get_scoped_or_404

    return send_out(get_scoped_or_404(db, EmailSend, send_id, user.tenant_id))


@router.get("/outbox")
def mock_outbox(user: User = Depends(require("shortlist:send")), db: Session = Depends(get_db)):
    rows = db.scalars(select(MockOutboxMessage).where(MockOutboxMessage.tenant_id == user.tenant_id)
                      .order_by(MockOutboxMessage.created_at.desc()).limit(100)).all()
    return [{"id": m.id, "email_send_id": m.email_send_id, "from": m.from_addr, "to": m.to_recipients,
             "cc": m.cc_recipients, "subject": m.subject, "body": m.body, "attachments": m.attachments,
             "created_at": _dt(m.created_at), "is_mock": True} for m in rows]
