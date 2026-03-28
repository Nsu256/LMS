from sqlalchemy.orm import Session

from app.models import AuditLog


def log_audit_event(
    db: Session,
    *,
    action: str,
    actor_type: str,
    user_id: int,
    resource: str,
    resource_id: int | None = None,
    details: str | None = None,
) -> AuditLog:
    entry = AuditLog(
        action=action,
        actor_type=actor_type,
        user_id=user_id,
        resource=resource,
        resource_id=resource_id,
        details=details,
    )
    db.add(entry)
    return entry
