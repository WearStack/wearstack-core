import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, require_permission
from app.db.session import get_db
from app.models import Customer
from app.services.audit import record_audit

router = APIRouter(prefix="/customers", tags=["customers"])


class CustomerIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    phone: str | None = Field(default=None, pattern=r"^\+?\d{7,15}$")
    email: EmailStr | None = None
    gstin: str | None = Field(default=None, pattern=r"^\d{2}[A-Z0-9]{13}$")
    state_code: str | None = Field(default=None, pattern=r"^\d{2}$")
    # Only true if the customer actually agreed to receive marketing messages.
    marketing_consent: bool = False


class CustomerUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    phone: str | None = Field(default=None, pattern=r"^\+?\d{7,15}$")
    email: EmailStr | None = None
    gstin: str | None = Field(default=None, pattern=r"^\d{2}[A-Z0-9]{13}$")
    state_code: str | None = Field(default=None, pattern=r"^\d{2}$")
    marketing_consent: bool | None = None
    is_active: bool | None = None


class CustomerOut(BaseModel):
    id: uuid.UUID
    name: str
    phone: str | None
    email: str | None
    gstin: str | None
    state_code: str | None
    marketing_consent: bool
    is_active: bool

    model_config = {"from_attributes": True}


def _get(db: Session, ctx: AuthContext, customer_id: uuid.UUID) -> Customer:
    c = db.get(Customer, customer_id)
    if c is None or c.business_id != ctx.business_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Customer not found")
    return c


@router.get("", response_model=list[CustomerOut])
def list_customers(
    q: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    ctx: AuthContext = Depends(require_permission("customer:read")),
    db: Session = Depends(get_db),
) -> Any:
    stmt = select(Customer).where(Customer.business_id == ctx.business_id)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Customer.name.ilike(like), Customer.phone.ilike(like)))
    return db.scalars(stmt.order_by(Customer.name).limit(limit).offset(offset)).all()


@router.post("", response_model=CustomerOut, status_code=status.HTTP_201_CREATED)
def create_customer(
    body: CustomerIn,
    ctx: AuthContext = Depends(require_permission("customer:write")),
    db: Session = Depends(get_db),
) -> Any:
    data = body.model_dump()
    customer = Customer(
        business_id=ctx.business_id,
        consent_at=datetime.now(UTC) if body.marketing_consent else None,
        **data,
    )
    db.add(customer)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "A customer with this phone exists") from None
    record_audit(
        db,
        business_id=ctx.business_id,
        user_id=ctx.user.id,
        action="customer.created",
        entity_type="customer",
        entity_id=customer.id,
        after={"name": customer.name, "marketing_consent": customer.marketing_consent},
    )
    db.commit()
    return customer


@router.patch("/{customer_id}", response_model=CustomerOut)
def update_customer(
    customer_id: uuid.UUID,
    body: CustomerUpdate,
    ctx: AuthContext = Depends(require_permission("customer:write")),
    db: Session = Depends(get_db),
) -> Any:
    customer = _get(db, ctx, customer_id)
    changes = body.model_dump(exclude_unset=True)
    before = {k: str(getattr(customer, k)) for k in changes}
    if (
        "marketing_consent" in changes
        and changes["marketing_consent"] != customer.marketing_consent
    ):
        customer.consent_at = datetime.now(UTC) if changes["marketing_consent"] else None
    for field, value in changes.items():
        setattr(customer, field, value)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "A customer with this phone exists") from None
    record_audit(
        db,
        business_id=ctx.business_id,
        user_id=ctx.user.id,
        action="customer.updated",
        entity_type="customer",
        entity_id=customer.id,
        before=before,
        after={k: str(v) for k, v in changes.items()},
    )
    db.commit()
    return customer
