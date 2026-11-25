import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, require_permission
from app.db.session import get_db
from app.models import AuditLog, User

router = APIRouter(prefix="/audit-logs", tags=["audit"])


class AuditOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID | None
    user_name: str | None  # who did it, by name
    action: str
    entity_type: str
    entity_id: uuid.UUID | None
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    created_at: datetime


@router.get("", response_model=list[AuditOut])
def list_audit_logs(
    entity_type: str | None = None,
    user_id: uuid.UUID | None = None,
    action_prefix: str | None = Query(default=None, max_length=40, description="e.g. 'user.'"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    ctx: AuthContext = Depends(require_permission("audit:read")),
    db: Session = Depends(get_db),
) -> list[AuditOut]:
    stmt = (
        select(AuditLog, User.full_name)
        .outerjoin(User, User.id == AuditLog.user_id)
        .where(AuditLog.business_id == ctx.business_id)
    )
    if entity_type:
        stmt = stmt.where(AuditLog.entity_type == entity_type)
    if user_id:
        stmt = stmt.where(AuditLog.user_id == user_id)
    if action_prefix:
        escaped = action_prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        stmt = stmt.where(AuditLog.action.like(f"{escaped}%", escape="\\"))
    rows = db.execute(
        stmt.order_by(AuditLog.created_at.desc(), AuditLog.id).limit(limit).offset(offset)
    )
    return [
        AuditOut(
            id=a.id,
            user_id=a.user_id,
            user_name=name,
            action=a.action,
            entity_type=a.entity_type,
            entity_id=a.entity_id,
            before=a.before,
            after=a.after,
            created_at=a.created_at,
        )
        for a, name in rows
    ]
