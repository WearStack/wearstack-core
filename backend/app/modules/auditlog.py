import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, require_permission
from app.db.session import get_db
from app.models import AuditLog

router = APIRouter(prefix="/audit-logs", tags=["audit"])


class AuditOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID | None
    action: str
    entity_type: str
    entity_id: uuid.UUID | None
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    created_at: datetime

    model_config = {"from_attributes": True}


@router.get("", response_model=list[AuditOut])
def list_audit_logs(
    entity_type: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    ctx: AuthContext = Depends(require_permission("audit:read")),
    db: Session = Depends(get_db),
) -> list[AuditLog]:
    stmt = select(AuditLog).where(AuditLog.business_id == ctx.business_id)
    if entity_type:
        stmt = stmt.where(AuditLog.entity_type == entity_type)
    stmt = stmt.order_by(AuditLog.created_at.desc()).limit(limit).offset(offset)
    return list(db.scalars(stmt))
