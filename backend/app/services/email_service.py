"""Shortlist email: recipient validation, preview, idempotent send and provider abstraction.

Milestone 1 ships a MOCK provider that writes to an in-database outbox. "accepted" means the
provider accepted the message; it is NOT confirmed delivery.
"""
import hashlib
import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass

from email_validator import EmailNotValidError, validate_email
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import audit
from app.config import get_settings
from app.db import utcnow
from app.models import Application, EmailSend, Evaluation, JobOpening, MockOutboxMessage, Task, Tenant, User
from app.scoring import from_e4, to_decimal
from app.services.tasks import PermanentTaskError, enqueue, register

MAX_RECIPIENTS = 50
MAX_CANDIDATES = 200


def parse_recipients(raw: str | list[str] | None) -> tuple[list[str], list[str]]:
    """Return (valid normalized addresses, invalid entries)."""
    if raw is None:
        return [], []
    parts = raw if isinstance(raw, list) else re.split(r"[,;\s]+", raw)
    valid, invalid = [], []
    for p in (x.strip() for x in parts):
        if not p:
            continue
        try:
            addr = validate_email(p, check_deliverability=False).normalized.lower()
            if addr not in valid:
                valid.append(addr)
        except EmailNotValidError:
            invalid.append(p)
    return valid, invalid


def external_recipients(addresses: list[str], allowed_domains: list[str]) -> list[str]:
    allowed = {d.lower().lstrip("@") for d in allowed_domains}
    return [a for a in addresses if a.rsplit("@", 1)[-1] not in allowed]


@dataclass
class ShortlistRequest:
    job_id: str
    application_ids: list[str]
    to: str | list[str]
    cc: str | list[str] | None
    subject: str
    message: str
    include_attachments: bool
    score_min: float | None
    score_max: float | None
    confirm_external_recipients: bool = False


def build_preview(db: Session, user: User, req: ShortlistRequest) -> dict:
    tenant = db.get(Tenant, user.tenant_id)
    job = db.get(JobOpening, req.job_id)
    if job is None or job.tenant_id != user.tenant_id:
        raise HTTPException(404, "JobOpening not found")
    errors: list[str] = []
    warnings: list[str] = []

    to, bad_to = parse_recipients(req.to)
    cc, bad_cc = parse_recipients(req.cc)
    if bad_to or bad_cc:
        errors.append(f"Invalid email address(es): {', '.join(bad_to + bad_cc)}")
    if not to:
        errors.append("Enter at least one valid recipient in To.")
    if len(to) + len(cc) > MAX_RECIPIENTS:
        errors.append(f"At most {MAX_RECIPIENTS} recipients are allowed.")
    if not req.subject.strip():
        errors.append("Subject is required.")

    ids = list(dict.fromkeys(req.application_ids))
    if not ids:
        errors.append("Select at least one candidate.")
    if len(ids) > MAX_CANDIDATES:
        errors.append(f"At most {MAX_CANDIDATES} candidates per email.")
    apps = db.scalars(select(Application).where(Application.tenant_id == user.tenant_id,
                                                Application.job_id == job.id, Application.id.in_(ids))).all() if ids else []
    if len(apps) != len(ids):
        errors.append("One or more selected applications were not found for this job.")
    order = {a: i for i, a in enumerate(ids)}
    apps = sorted(apps, key=lambda a: order[a.id])

    external = external_recipients(to + cc, tenant.allowed_email_domains or [])
    if external:
        warnings.append(
            "These recipients are outside your organization's configured domains and would receive "
            f"candidate data: {', '.join(external)}. Explicit confirmation is required to send."
        )
    attachments_allowed = bool(tenant.allow_resume_attachments) and user.role in ("admin", "recruiter")
    if req.include_attachments and not attachments_allowed:
        errors.append("Resume attachments are disabled by your organization's settings. Secure links will be used.")

    lo = to_decimal(req.score_min) if req.score_min is not None else None
    hi = to_decimal(req.score_max) if req.score_max is not None else None
    base = get_settings().app_base_url.rstrip("/")
    candidates = []
    for a in apps:
        ev = db.scalar(select(Evaluation).where(Evaluation.application_id == a.id, Evaluation.is_current.is_(True),
                                                Evaluation.tenant_id == user.tenant_id))
        score = from_e4(ev.score_e4) if ev else None
        if ev and lo is not None and hi is not None and not (lo <= to_decimal(ev.score_e4) / 10000 <= hi):
            warnings.append(f"{_name(a)} ({ev.score_e4 / 10000:.4f}) is outside the active score range.")
        if ev is None:
            warnings.append(f"{_name(a)} has no score (status: {a.status}).")
        candidates.append({
            "application_id": a.id,
            "candidate_name": _name(a),
            "score": score,
            "score_exact": f"{ev.score_e4 / 10000:.4f}" if ev else None,
            "required_status": ev.required_status if ev else None,
            "supported_skills": (ev.supported_terms if ev else [])[:8],
            "is_mock": ev.is_mock if ev else None,
            "link": f"{base}/applications/{a.id}",
            "attachment": a.document.original_filename if (req.include_attachments and attachments_allowed and a.document) else None,
        })
    if any(c["is_mock"] for c in candidates):
        warnings.append("Scores in this shortlist come from DEMO MOCK scoring, not real AI evaluation.")

    rendered = _render(job, req, candidates)
    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "requires_external_confirmation": bool(external),
        "to": to,
        "cc": cc,
        "external_recipients": external,
        "job": {"id": job.id, "title": job.title},
        "score_range": {"min": req.score_min, "max": req.score_max},
        "candidate_count": len(candidates),
        "candidates": candidates,
        "subject": req.subject.strip(),
        "rendered_text": rendered,
        "attachments_allowed": attachments_allowed,
        "delivery_mode": "attachments" if (req.include_attachments and attachments_allowed) else "secure_links",
    }


def _name(a: Application) -> str:
    return (a.candidate.full_name if a.candidate else None) or "(name not detected)"


def _render(job: JobOpening, req: ShortlistRequest, candidates: list[dict]) -> str:
    lines = [req.message.strip(), "", f"Job opening: {job.title}"]
    if req.score_min is not None and req.score_max is not None:
        lines.append(f"Score range applied: {req.score_min:g} - {req.score_max:g} (inclusive, rubric alignment score)")
    lines.append(f"Candidates: {len(candidates)}")
    lines.append("")
    for i, c in enumerate(candidates, start=1):
        score = c["score_exact"] or "not scored"
        lines.append(f"{i}. {c['candidate_name']} - alignment score {score} - required criteria: {c['required_status'] or 'n/a'}")
        if c["supported_skills"]:
            lines.append(f"   Supported skills: {', '.join(c['supported_skills'])}")
        lines.append(f"   Application (sign-in required): {c['link']}")
        if c["attachment"]:
            lines.append(f"   Attachment: {c['attachment']}")
    lines += ["", "Alignment scores measure evidence against the approved rubric. They are not hiring "
              "probabilities and do not replace recruiter judgement."]
    if any(c["is_mock"] for c in candidates):
        lines.append("NOTE: scores were produced by DEMO MOCK scoring, not real AI evaluation.")
    return "\n".join(lines)


def _fingerprint(preview: dict, req: ShortlistRequest) -> str:
    payload = {"to": preview["to"], "cc": preview["cc"], "subject": preview["subject"], "message": req.message,
               "ids": [c["application_id"] for c in preview["candidates"]], "att": req.include_attachments}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def request_send(db: Session, user: User, req: ShortlistRequest, idempotency_key: str) -> tuple[EmailSend, bool]:
    """Returns (send, created). Re-using an idempotency key returns the original send."""
    if not idempotency_key or not (8 <= len(idempotency_key) <= 100):
        raise HTTPException(400, "An Idempotency-Key header (8-100 chars) is required.")
    existing = db.scalar(select(EmailSend).where(EmailSend.tenant_id == user.tenant_id,
                                                 EmailSend.idempotency_key == idempotency_key))
    preview = build_preview(db, user, req)
    fp = _fingerprint(preview, req)
    if existing:
        if existing.request_fingerprint != fp:
            raise HTTPException(409, "This idempotency key was already used for a different email.")
        return existing, False
    if not preview["valid"]:
        raise HTTPException(422, {"message": "Email cannot be sent", "errors": preview["errors"]})
    if preview["requires_external_confirmation"] and not req.confirm_external_recipients:
        raise HTTPException(409, {"message": "External recipients require confirmation",
                                  "external_recipients": preview["external_recipients"]})
    send = EmailSend(
        tenant_id=user.tenant_id, job_id=req.job_id, sender_id=user.id, sender_email=user.email,
        idempotency_key=idempotency_key, request_fingerprint=fp, to_recipients=preview["to"],
        cc_recipients=preview["cc"], external_recipients=preview["external_recipients"],
        subject=preview["subject"], body_text=req.message, rendered_text=preview["rendered_text"],
        include_attachments=preview["delivery_mode"] == "attachments", score_min=req.score_min,
        score_max=req.score_max, application_ids=[c["application_id"] for c in preview["candidates"]],
        status="queued", provider=get_email_provider().name,
    )
    db.add(send)
    try:
        db.flush()
    except IntegrityError:  # concurrent double-submit with the same key
        db.rollback()
        existing = db.scalar(select(EmailSend).where(EmailSend.tenant_id == user.tenant_id,
                                                     EmailSend.idempotency_key == idempotency_key))
        return existing, False
    enqueue(db, user.tenant_id, "send_email", {"email_send_id": send.id}, max_attempts=3)
    audit.record(db, tenant_id=user.tenant_id, user=user, action="shortlist.send_requested", entity_type="email_send",
                 entity_id=send.id, details={"job_id": req.job_id, "recipients": preview["to"] + preview["cc"],
                                             "external_recipients": preview["external_recipients"],
                                             "application_ids": send.application_ids,
                                             "score_range": [req.score_min, req.score_max],
                                             "delivery_mode": preview["delivery_mode"]})
    db.commit()
    return send, True


# ---- providers -------------------------------------------------------------------------------

@dataclass
class ProviderResult:
    accepted: bool
    message_id: str | None = None
    error: str | None = None


class EmailProvider(ABC):
    name: str

    @abstractmethod
    def send(self, db: Session, send: EmailSend) -> ProviderResult: ...


class MockOutboxProvider(EmailProvider):
    name = "mock_outbox"

    def send(self, db: Session, send: EmailSend) -> ProviderResult:
        apps = db.scalars(select(Application).where(Application.tenant_id == send.tenant_id,
                                                    Application.id.in_(send.application_ids))).all()
        attachments = [a.document.original_filename for a in apps if send.include_attachments and a.document]
        msg = MockOutboxMessage(tenant_id=send.tenant_id, email_send_id=send.id,
                                from_addr=get_settings().email_from, to_recipients=send.to_recipients,
                                cc_recipients=send.cc_recipients, subject=send.subject, body=send.rendered_text,
                                attachments=attachments)
        db.add(msg)
        db.flush()
        return ProviderResult(accepted=True, message_id=f"mock-{msg.id}")


def get_email_provider() -> EmailProvider:
    name = get_settings().email_provider.lower()
    if name == "mock":
        return MockOutboxProvider()
    raise RuntimeError(f"Email provider '{name}' is not implemented in this milestone. Set EMAIL_PROVIDER=mock.")


def _on_send_failure(db: Session, task: Task, error: str) -> None:
    send = db.get(EmailSend, task.payload.get("email_send_id"))
    if send is not None and send.tenant_id == task.tenant_id:
        send.status = "failed"
        send.failure_detail = error
        audit.record(db, tenant_id=send.tenant_id, action="shortlist.send_failed", entity_type="email_send",
                     entity_id=send.id, details={"error": error})


@register("send_email", on_failure=_on_send_failure)
def handle_send_email(db: Session, task: Task) -> None:
    send = db.get(EmailSend, task.payload.get("email_send_id"))
    if send is None or send.tenant_id != task.tenant_id:
        raise PermanentTaskError("Email send not found for this tenant")
    if send.status == "accepted":
        return  # already sent; retries must never send twice
    send.status = "sending"
    result = get_email_provider().send(db, send)
    if not result.accepted:
        raise RuntimeError(result.error or "Provider rejected the message")
    send.status = "accepted"
    send.provider_message_id = result.message_id
    send.accepted_at = utcnow()
    send.delivery_status = "unknown"
    audit.record(db, tenant_id=send.tenant_id, action="shortlist.accepted_by_provider", entity_type="email_send",
                 entity_id=send.id, details={"provider": send.provider, "message_id": result.message_id})
