"""Connector sync: list source records, then ingest each one as its own retryable task."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit
from app.db import utcnow
from app.files import UploadRejected
from app.ingestion.base import PermanentSourceError, TransientSourceError
from app.ingestion.mock_ats import get_adapter
from app.models import Application, IntegrationConfig, JobOpening, Task, User
from app.services.pipeline import ingest_document
from app.services.tasks import PermanentTaskError, TransientTaskError, enqueue, register


def start_sync(db: Session, user: User, kind: str) -> dict:
    adapter = get_adapter(kind)
    records = adapter.list_records()
    queued, skipped = 0, 0
    for r in records:
        exists = db.scalar(select(Application.id).where(
            Application.tenant_id == user.tenant_id, Application.source_system == kind,
            Application.external_application_id == r.external_application_id))
        pending = db.scalar(select(Task.id).where(
            Task.tenant_id == user.tenant_id, Task.type == "connector_ingest",
            Task.status.in_(["queued", "running"]), Task.payload["record_id"].as_string() == r.record_id))
        if exists or pending:
            skipped += 1
            continue
        enqueue(db, user.tenant_id, "connector_ingest", {"kind": kind, "record_id": r.record_id}, max_attempts=3)
        queued += 1
    cfg = db.scalar(select(IntegrationConfig).where(IntegrationConfig.tenant_id == user.tenant_id,
                                                    IntegrationConfig.kind == kind))
    result = {"records_found": len(records), "queued": queued, "skipped_existing": skipped}
    if cfg:
        cfg.last_sync_at = utcnow()
        cfg.last_result = result
        cfg.status = "sync_requested"
    audit.record(db, tenant_id=user.tenant_id, user=user, action="integration.sync_started",
                 entity_type="integration", entity_id=kind, details=result)
    return result


def _on_ingest_failure(db: Session, task: Task, error: str) -> None:
    audit.record(db, tenant_id=task.tenant_id, action="integration.ingest_failed", entity_type="integration",
                 entity_id=task.payload.get("kind"), details={"record_id": task.payload.get("record_id"),
                                                              "attempts": task.attempts, "error": error})


@register("connector_ingest", on_failure=_on_ingest_failure)
def handle_connector_ingest(db: Session, task: Task) -> None:
    kind, record_id = task.payload["kind"], task.payload["record_id"]
    try:
        adapter = get_adapter(kind)
        record = adapter.get_record(record_id)
        job = db.scalar(select(JobOpening).where(JobOpening.tenant_id == task.tenant_id,
                                                 JobOpening.external_ref == record.job_external_ref))
        if job is None:
            raise PermanentSourceError(f"No job opening mapped to external ref {record.job_external_ref}")
        filename, data = adapter.fetch_document(record, task.attempts)
        ingest_document(db, tenant_id=task.tenant_id, job=job, filename=filename, data=data,
                        source_system=kind, submitted_at=record.submitted_at,
                        external_application_id=record.external_application_id,
                        external_candidate_id=record.external_candidate_id)
    except TransientSourceError as e:
        raise TransientTaskError(str(e))
    except (PermanentSourceError, UploadRejected) as e:
        raise PermanentTaskError(str(e))


# ---- recruitment mailbox (IMAP, read-only) --------------------------------------------------

IMAP_KIND = "imap_mailbox"
IMAP_SOURCE = "mailbox_imap"


def imap_settings_for(cfg: IntegrationConfig):
    from app.ingestion.imap_mailbox import ImapSettings

    s = cfg.settings or {}
    if not (s.get("host") and s.get("username")):
        raise PermanentSourceError("IMAP host and username are not configured.")
    return ImapSettings(host=s["host"], port=int(s.get("port", 993)), username=s["username"],
                        folder=s.get("folder", "INBOX"), since_days=int(s.get("since_days", 30)))


@register("imap_sync", on_failure=_on_ingest_failure)
def handle_imap_sync(db: Session, task: Task) -> None:
    from datetime import timedelta

    from app.config import get_settings
    from app.ingestion.email_intake import ingest_email
    from app.ingestion.imap_mailbox import fetch_messages

    cfg = db.scalar(select(IntegrationConfig).where(IntegrationConfig.tenant_id == task.tenant_id,
                                                    IntegrationConfig.kind == IMAP_KIND))
    if cfg is None or not cfg.enabled:
        raise PermanentTaskError("IMAP mailbox integration is not enabled for this tenant.")
    password = get_settings().mailbox_imap_password
    if not password:
        raise PermanentTaskError("MAILBOX_IMAP_PASSWORD is not set on the server.")
    try:
        settings = imap_settings_for(cfg)
        _, messages = fetch_messages(settings, password, (utcnow() - timedelta(days=settings.since_days)).date())
    except TransientSourceError as e:
        raise TransientTaskError(str(e))
    except PermanentSourceError as e:
        cfg.status, cfg.last_result = "error", {"error": str(e)}
        db.commit()
        raise PermanentTaskError(str(e))
    counts: dict[str, int] = {}
    for record_key, raw in messages:
        try:
            with db.begin_nested():  # one bad message must not roll back the others
                rec = ingest_email(db, tenant_id=task.tenant_id, raw=raw, source=IMAP_SOURCE, record_key=record_key)
                outcome = rec.outcome
        except UploadRejected:
            outcome = "rejected_message"
        counts[outcome] = counts.get(outcome, 0) + 1
    cfg.status, cfg.last_sync_at = "synced", utcnow()
    cfg.last_result = {"messages_seen": len(messages), **counts}
