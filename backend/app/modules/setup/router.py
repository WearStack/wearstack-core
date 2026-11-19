import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.db.session import get_db
from app.models import Business, Store, User, UserStoreAccess
from app.services.audit import record_audit
from app.services.rbac import create_default_roles

router = APIRouter(prefix="/setup", tags=["setup"])

_SETUP_LOCK = 748_201  # arbitrary advisory-lock key, serialises concurrent first-run requests


class SetupRequest(BaseModel):
    business_name: str = Field(min_length=1, max_length=200)
    state_code: str = Field(pattern=r"^\d{2}$")
    gstin: str | None = Field(default=None, pattern=r"^\d{2}[A-Z0-9]{13}$")
    store_name: str = Field(min_length=1, max_length=200)
    store_code: str = Field(min_length=1, max_length=20)
    owner_name: str = Field(min_length=1, max_length=200)
    owner_email: EmailStr
    owner_password: str = Field(min_length=10, max_length=128)


class SetupResponse(BaseModel):
    business_id: uuid.UUID
    store_id: uuid.UUID
    owner_id: uuid.UUID


class SetupStatus(BaseModel):
    setup_required: bool


@router.get("/status", response_model=SetupStatus)
def setup_status(db: Session = Depends(get_db)) -> SetupStatus:
    return SetupStatus(setup_required=not db.scalar(select(func.count()).select_from(Business)))


@router.post("", response_model=SetupResponse, status_code=status.HTTP_201_CREATED)
def run_setup(body: SetupRequest, db: Session = Depends(get_db)) -> SetupResponse:
    """First-run bootstrap. Locks itself permanently once any business exists."""
    db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _SETUP_LOCK})
    if db.scalar(select(func.count()).select_from(Business)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Setup has already been completed")

    business = Business(name=body.business_name, gstin=body.gstin, state_code=body.state_code)
    db.add(business)
    db.flush()
    store = Store(
        business_id=business.id,
        code=body.store_code,
        name=body.store_name,
        state_code=body.state_code,
        gstin=body.gstin,
    )
    roles = create_default_roles(db, business.id)
    owner = User(
        business_id=business.id,
        role_id=roles["Owner"].id,
        email=body.owner_email.lower(),
        full_name=body.owner_name,
        password_hash=hash_password(body.owner_password),
    )
    db.add_all([store, owner])
    db.flush()
    db.add(UserStoreAccess(user_id=owner.id, store_id=store.id))
    record_audit(
        db,
        business_id=business.id,
        user_id=owner.id,
        action="setup.completed",
        entity_type="business",
        entity_id=business.id,
        after={"business": body.business_name, "store": body.store_code},
    )
    db.commit()
    return SetupResponse(business_id=business.id, store_id=store.id, owner_id=owner.id)
