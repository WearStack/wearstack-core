import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, require_permission
from app.core.gstin import validate_gstin
from app.db.session import get_db
from app.models import Business
from app.services.audit import record_audit

router = APIRouter(prefix="/business", tags=["business"])


class BusinessOut(BaseModel):
    id: uuid.UUID
    name: str
    legal_name: str | None
    gstin: str | None
    state_code: str

    model_config = {"from_attributes": True}


class BusinessUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    legal_name: str | None = Field(default=None, max_length=200)
    gstin: str | None = None

    _check_gstin = field_validator("gstin")(validate_gstin)


def _get(db: Session, ctx: AuthContext) -> Business:
    business = db.get(Business, ctx.business_id)
    if business is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Business not found")
    return business


@router.get("", response_model=BusinessOut)
def get_business(
    ctx: AuthContext = Depends(require_permission("store:read")), db: Session = Depends(get_db)
) -> Business:
    return _get(db, ctx)


@router.patch("", response_model=BusinessOut)
def update_business(
    body: BusinessUpdate,
    ctx: AuthContext = Depends(require_permission("store:write")),
    db: Session = Depends(get_db),
) -> Business:
    """The business GSTIN is the fallback seller GSTIN for stores that have none of their own."""
    business = _get(db, ctx)
    changes = body.model_dump(exclude_unset=True)
    if "name" in changes and changes["name"] is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "The name cannot be empty")
    before = {k: getattr(business, k) for k in changes}
    for field, value in changes.items():
        setattr(business, field, value)
    record_audit(
        db,
        business_id=ctx.business_id,
        user_id=ctx.user.id,
        action="business.updated",
        entity_type="business",
        entity_id=business.id,
        before=before,
        after=changes,
    )
    db.commit()
    return business
