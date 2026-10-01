"""Data retention and deletion. Deletes application data, stored documents and evaluations.
Audit entries are kept (they contain no resume content)."""
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit
from app.db import utcnow
from app.models import Application, Candidate, Tenant, User
from app.storage import get_storage


def delete_application(db: Session, app: Application, user: User | None, reason: str) -> None:
    storage = get_storage()
    if app.document is not None:
        storage.delete(app.tenant_id, app.document.storage_key)
    cand_id = app.candidate_id
    app_id, tenant_id = app.id, app.tenant_id
    db.delete(app)
    db.flush()
    if cand_id and not db.scalar(select(Application.id).where(Application.candidate_id == cand_id).limit(1)):
        cand = db.get(Candidate, cand_id)
        if cand is not None:
            db.delete(cand)
    audit.record(db, tenant_id=tenant_id, user=user, action="application.deleted", entity_type="application",
                 entity_id=app_id, details={"reason": reason})


def run_retention(db: Session, tenant: Tenant, user: User | None) -> int:
    cutoff = utcnow() - timedelta(days=tenant.retention_days)
    old = db.scalars(select(Application).where(Application.tenant_id == tenant.id,
                                               Application.submitted_at < cutoff)).all()
    for app in old:
        delete_application(db, app, user, reason=f"retention ({tenant.retention_days} days)")
    audit.record(db, tenant_id=tenant.id, user=user, action="retention.run", entity_type="tenant",
                 entity_id=tenant.id, details={"deleted": len(old), "retention_days": tenant.retention_days})
    return len(old)
