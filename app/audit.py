from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import Request
from sqlalchemy.orm import Session

from app.models import AuditLog

if TYPE_CHECKING:
    from app.deps import Principal


def client_ip(request: Request | None) -> str:
    if request is None or request.client is None:
        return "unknown"
    # Behind the approved reverse proxy, uvicorn's --proxy-headers sets client.host.
    return request.client.host


def audit(
    db: Session,
    action: str,
    *,
    principal: "Principal | None" = None,
    actor_user_id: int | None = None,
    actor_role: str | None = None,
    request: Request | None = None,
    entity_type: str | None = None,
    entity_id: Any = None,
    outcome: str = "success",
    **details: Any,
) -> AuditLog:
    """Stage an audit row in the caller's transaction (caller commits)."""
    if principal is not None:
        actor_user_id = principal.user.id
        actor_role = principal.role
    row = AuditLog(
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        action=action,
        entity_type=entity_type,
        entity_id=None if entity_id is None else str(entity_id),
        outcome=outcome,
        details=details,
        ip=client_ip(request),
    )
    db.add(row)
    return row
