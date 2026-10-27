"""Audit logging. Never put resume text, document contents or credentials in `details`."""
from sqlalchemy.orm import Session

from app.models import AuditLog, User


def record(
    db: Session,
    *,
    tenant_id: str,
    action: str,
    user: User | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    details: dict | None = None,
) -> None:
    db.add(
        AuditLog(
            tenant_id=tenant_id,
            user_id=user.id if user else None,
            actor_email=user.email if user else "system",
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            details=details or {},
        )
    )
