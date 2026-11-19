import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, require_permission
from app.db.session import get_db
from app.models import Store, UserStoreAccess
from app.services.audit import record_audit

router = APIRouter(prefix="/stores", tags=["stores"])


class StoreIn(BaseModel):
    code: str = Field(min_length=1, max_length=20)
    name: str = Field(min_length=1, max_length=200)
    address: str | None = Field(default=None, max_length=500)
    state_code: str = Field(pattern=r"^\d{2}$")
    gstin: str | None = Field(default=None, pattern=r"^\d{2}[A-Z0-9]{13}$")


class StoreUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    address: str | None = Field(default=None, max_length=500)
    gstin: str | None = Field(default=None, pattern=r"^\d{2}[A-Z0-9]{13}$")
    is_active: bool | None = None


class StoreOut(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    address: str | None
    state_code: str
    gstin: str | None
    is_active: bool

    model_config = {"from_attributes": True}


def _snapshot(s: Store) -> dict[str, object]:
    return StoreOut.model_validate(s).model_dump(mode="json")


@router.get("", response_model=list[StoreOut])
def list_stores(
    ctx: AuthContext = Depends(require_permission("store:read")), db: Session = Depends(get_db)
) -> list[Store]:
    stmt = select(Store).where(Store.id.in_(ctx.store_ids)).order_by(Store.code)
    return list(db.scalars(stmt))


@router.post("", response_model=StoreOut, status_code=status.HTTP_201_CREATED)
def create_store(
    body: StoreIn,
    ctx: AuthContext = Depends(require_permission("store:write")),
    db: Session = Depends(get_db),
) -> Store:
    store = Store(business_id=ctx.business_id, **body.model_dump())
    db.add(store)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Store code already exists") from None
    db.add(UserStoreAccess(user_id=ctx.user.id, store_id=store.id))
    record_audit(
        db,
        business_id=ctx.business_id,
        user_id=ctx.user.id,
        action="store.created",
        entity_type="store",
        entity_id=store.id,
        after=_snapshot(store),
    )
    db.commit()
    return store


@router.patch("/{store_id}", response_model=StoreOut)
def update_store(
    store_id: uuid.UUID,
    body: StoreUpdate,
    ctx: AuthContext = Depends(require_permission("store:write")),
    db: Session = Depends(get_db),
) -> Store:
    ctx.require_store(store_id)
    store = db.get(Store, store_id)
    if store is None or store.business_id != ctx.business_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Store not found")
    before = _snapshot(store)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(store, field, value)
    record_audit(
        db,
        business_id=ctx.business_id,
        user_id=ctx.user.id,
        action="store.updated",
        entity_type="store",
        entity_id=store.id,
        before=before,
        after=_snapshot(store),
    )
    db.commit()
    return store
