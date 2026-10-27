"""Recruitment-mailbox intake: turn application emails into applications.

Only resume ATTACHMENTS are scored. The email body and subject are untrusted and are used solely
to route the message to a job (by requisition ref or exact job title). Sender addresses are not
authenticated (no DKIM/SPF verification in this milestone), so they are used only as a candidate
contact hint, never for scoring.
"""
import email
import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email import policy
from email.utils import getaddresses, parsedate_to_datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit
from app.config import get_settings
from app.files import ALLOWED_TYPES, UploadRejected, sanitize_filename
from app.models import IngestedMessage, JobOpening, Tenant, User
from app.services.pipeline import ingest_document

_COVER_LETTER_RE = re.compile(r"cover[\s_-]*letter|\bcover\b|\bcl\b", re.IGNORECASE)


@dataclass
class ParsedEmail:
    message_id: str
    message_id_hash: str
    sender_email: str | None
    subject: str
    received_at: datetime | None
    attachments: list[tuple[str, bytes]] = field(default_factory=list)  # (filename, data) PDF/DOCX only
    skipped_attachments: list[str] = field(default_factory=list)


def parse_email(raw: bytes) -> ParsedEmail:
    msg = email.message_from_bytes(raw, policy=policy.default)
    mid = (msg.get("Message-ID") or "").strip()
    # Without a Message-ID, hash the full message so identical re-imports still dedupe.
    mid_hash = hashlib.sha256((mid or "").encode() if mid else raw).hexdigest()
    senders = getaddresses([msg.get("Reply-To") or msg.get("From") or ""])
    sender = senders[0][1].strip().lower() if senders and "@" in senders[0][1] else None
    received = None
    try:
        if msg.get("Date"):
            d = parsedate_to_datetime(msg["Date"])
            received = (d.astimezone(timezone.utc) if d.tzinfo else d).replace(tzinfo=None)
    except (TypeError, ValueError):
        received = None
    parsed = ParsedEmail(mid, mid_hash, sender, " ".join(str(msg.get("Subject") or "").split())[:300], received)
    for part in msg.iter_attachments():
        name = sanitize_filename(part.get_filename() or "attachment")
        ext = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
        if ext not in ALLOWED_TYPES:
            parsed.skipped_attachments.append(f"{name} (unsupported type)")
            continue
        data = part.get_payload(decode=True) or b""
        parsed.attachments.append((name, data))
    return parsed


def pick_resume(attachments: list[tuple[str, bytes]]) -> tuple[tuple[str, bytes] | None, list[str]]:
    """Prefer attachments not named like a cover letter. Returns (resume, notes)."""
    if not attachments:
        return None, []
    non_cover = [a for a in attachments if not _COVER_LETTER_RE.search(a[0])]
    candidates = non_cover or attachments
    notes = []
    if len(candidates) > 1:
        notes.append(f"{len(candidates)} possible resume attachments; used '{candidates[0][0]}'. Review the others manually.")
    if not non_cover:
        notes.append("Only attachments named like a cover letter were found; used the first one.")
    return candidates[0], notes


def match_job(db: Session, tenant_id: str, subject: str) -> tuple[JobOpening | None, str | None]:
    """Route by requisition reference first, then by a unique exact job-title match."""
    jobs = db.scalars(select(JobOpening).where(JobOpening.tenant_id == tenant_id, JobOpening.status == "open")).all()
    s = subject.lower()
    by_ref = [j for j in jobs if j.external_ref and re.search(rf"(?<![\w-]){re.escape(j.external_ref.lower())}(?![\w-])", s)]
    if len(by_ref) == 1:
        return by_ref[0], None
    titled = [j for j in jobs if j.title.lower() in s]
    if titled:
        longest = max(len(j.title) for j in titled)
        titled = [j for j in titled if len(j.title) == longest]
    if len(titled) == 1:
        return titled[0], None
    if len(titled) > 1:
        refs = ", ".join(j.external_ref or j.id[:8] for j in titled)
        return None, f"Subject matches {len(titled)} open jobs titled '{titled[0].title}'. Add a requisition ref ({refs}) or assign the job on import."
    return None, "Subject does not mention an open job title or requisition reference."


def ingest_email(
    db: Session, *, tenant_id: str, raw: bytes, source: str, record_key: str | None = None,
    user: User | None = None, job_override: JobOpening | None = None,
) -> IngestedMessage:
    """Idempotent: the same message (same source key, or same Message-ID from any source) is
    recorded once and never creates duplicate applications."""
    if len(raw) > get_settings().max_email_mb * 1024 * 1024:
        raise UploadRejected(f"Email exceeds the {get_settings().max_email_mb} MB limit.")
    parsed = parse_email(raw)
    key = record_key or parsed.message_id_hash
    existing = db.scalar(select(IngestedMessage).where(
        IngestedMessage.tenant_id == tenant_id, IngestedMessage.source == source, IngestedMessage.record_key == key))
    if existing and not (existing.outcome == "unmapped_job" and job_override is not None):
        return existing
    if existing:
        # A recruiter explicitly assigned a job to a message that could not be routed: process it now.
        rec = existing
        rec.outcome, rec.detail = "pending", None
    else:
        rec = IngestedMessage(tenant_id=tenant_id, source=source, record_key=key, message_id_hash=parsed.message_id_hash,
                              sender_email=parsed.sender_email, subject=parsed.subject, received_at=parsed.received_at,
                              outcome="pending", application_ids=[])
        db.add(rec)

    earlier = db.scalar(select(IngestedMessage).where(
        IngestedMessage.tenant_id == tenant_id, IngestedMessage.message_id_hash == parsed.message_id_hash,
        IngestedMessage.outcome == "imported"))
    if earlier:
        rec.outcome, rec.detail = "duplicate_message", f"Already imported via {earlier.source}."
        rec.job_id, rec.application_ids = earlier.job_id, earlier.application_ids
        return _finish(db, rec, user)

    resume, notes = pick_resume(parsed.attachments)
    if resume is None:
        rec.outcome = "no_resume_attachment"
        rec.detail = "No PDF or DOCX attachment." + (f" Skipped: {', '.join(parsed.skipped_attachments)}." if parsed.skipped_attachments else "")
        return _finish(db, rec, user)

    if job_override is not None:
        assert job_override.tenant_id == tenant_id
        job, why = job_override, None
    else:
        job, why = match_job(db, tenant_id, parsed.subject)
    if job is None:
        rec.outcome, rec.detail = "unmapped_job", why
        return _finish(db, rec, user)
    rec.job_id = job.id

    tenant = db.get(Tenant, tenant_id)
    internal = {d.lower() for d in (tenant.allowed_email_domains or [])}
    # A recruiter forwarding a resume is not the candidate.
    cand_email = parsed.sender_email if parsed.sender_email and parsed.sender_email.rsplit("@", 1)[-1] not in internal else None
    try:
        res = ingest_document(
            db, tenant_id=tenant_id, job=job, filename=resume[0], data=resume[1], source_system=source,
            user=user, submitted_at=parsed.received_at,
            external_application_id=f"{parsed.message_id_hash[:40]}:0", candidate_email=cand_email,
        )
    except UploadRejected as e:
        rec.outcome, rec.detail = "rejected_file", f"{resume[0]}: {e}"
        return _finish(db, rec, user)
    rec.outcome = "imported"
    rec.application_ids = [res.application.id]
    rec.detail = " ".join(notes + ([f"Skipped attachments: {', '.join(parsed.skipped_attachments)}."]
                                    if parsed.skipped_attachments else [])) or None
    return _finish(db, rec, user)


def _finish(db: Session, rec: IngestedMessage, user: User | None) -> IngestedMessage:
    audit.record(db, tenant_id=rec.tenant_id, user=user, action="mailbox.message_processed",
                 entity_type="ingested_message", entity_id=rec.id,
                 details={"source": rec.source, "outcome": rec.outcome, "job_id": rec.job_id,
                          "applications": len(rec.application_ids)})
    return rec
