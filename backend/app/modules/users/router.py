import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, require_permission
from app.core.permissions import OWNER_ROLE
from app.core.security import hash_password
from app.db.session import get_db
from app.models import RefreshToken, Role, Store, User, UserStoreAccess
from app.services.audit import record_audit

router = APIRouter(prefix="/users", tags=["users"])


class UserIn(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=10, max_length=128)
    role_id: uuid.UUID
    store_ids: list[uuid.UUID] = []


class UserUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=200)
    password: str | None = Field(default=None, min_length=10, max_length=128)
    role_id: uuid.UUID | None = None
    is_active: bool | None = None
    store_ids: list[uuid.UUID] | None = None


class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str
    role_id: uuid.UUID
    is_active: bool
    store_ids: list[uuid.UUID]


def _out(db: Session, u: User) -> UserOut:
    stores = db.scalars(select(UserStoreAccess.store_id).where(UserStoreAccess.user_id == u.id))
    return UserOut(
        id=u.id,
        email=u.email,
        full_name=u.full_name,
        role_id=u.role_id,
        is_active=u.is_active,
        store_ids=sorted(stores),
    )


def _is_owner_role(role: Role) -> bool:
    return role.is_system and role.name == OWNER_ROLE


def _role_for(db: Session, ctx: AuthContext, role_id: uuid.UUID) -> Role:
    role = db.get(Role, role_id)
    if role is None or role.business_id != ctx.business_id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Unknown role")
    if _is_owner_role(role) and not _is_owner_role(ctx.role):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only an Owner can assign the Owner role")
    return role


def _check_stores(db: Session, ctx: AuthContext, store_ids: list[uuid.UUID]) -> None:
    found = db.scalar(
        select(func.count())
        .select_from(Store)
        .where(Store.id.in_(store_ids), Store.business_id == ctx.business_id)
    )
    if found != len(set(store_ids)):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Unknown store")


def _set_stores(db: Session, user_id: uuid.UUID, store_ids: list[uuid.UUID]) -> None:
    db.execute(delete(UserStoreAccess).where(UserStoreAccess.user_id == user_id))
    db.add_all(UserStoreAccess(user_id=user_id, store_id=s) for s in set(store_ids))


def _active_owner_count(db: Session, business_id: uuid.UUID) -> int:
    stmt = (
        select(func.count())
        .select_from(User)
        .join(Role, Role.id == User.role_id)
        .where(
            User.business_id == business_id,
            User.is_active.is_(True),
            Role.is_system.is_(True),
            Role.name == OWNER_ROLE,
        )
    )
    return db.scalar(stmt) or 0


@router.get("", response_model=list[UserOut])
def list_users(
    ctx: AuthContext = Depends(require_permission("user:read")), db: Session = Depends(get_db)
) -> list[UserOut]:
    users = db.scalars(select(User).where(User.business_id == ctx.business_id).order_by(User.email))
    return [_out(db, u) for u in users]


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(
    body: UserIn,
    ctx: AuthContext = Depends(require_permission("user:write")),
    db: Session = Depends(get_db),
) -> UserOut:
    _role_for(db, ctx, body.role_id)
    _check_stores(db, ctx, body.store_ids)
    user = User(
        business_id=ctx.business_id,
        role_id=body.role_id,
        email=body.email.lower(),
        full_name=body.full_name,
        password_hash=hash_password(body.password),
    )
    db.add(user)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already in use") from None
    _set_stores(db, user.id, body.store_ids)
    record_audit(
        db,
        business_id=ctx.business_id,
        user_id=ctx.user.id,
        action="user.created",
        entity_type="user",
        entity_id=user.id,
        after={"email": user.email, "role_id": str(user.role_id)},
    )
    db.commit()
    return _out(db, user)


@router.patch("/{user_id}", response_model=UserOut)
def update_user(
    user_id: uuid.UUID,
    body: UserUpdate,
    ctx: AuthContext = Depends(require_permission("user:write")),
    db: Session = Depends(get_db),
) -> UserOut:
    user = db.get(User, user_id)
    if user is None or user.business_id != ctx.business_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    current_role = db.get(Role, user.role_id)
    assert current_role is not None
    if _is_owner_role(current_role) and not _is_owner_role(ctx.role):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only an Owner can modify an Owner")

    before = _out(db, user).model_dump(mode="json")
    changes = body.model_dump(exclude_unset=True)
    new_role = _role_for(db, ctx, body.role_id) if body.role_id else current_role
    deactivating = body.is_active is False and user.is_active
    demoting = _is_owner_role(current_role) and not _is_owner_role(new_role)
    if (deactivating or demoting) and _is_owner_role(current_role):
        if user.id == ctx.user.id and deactivating:
            raise HTTPException(status.HTTP_409_CONFLICT, "You cannot deactivate yourself")
        if _active_owner_count(db, ctx.business_id) <= 1:
            raise HTTPException(status.HTTP_409_CONFLICT, "The business needs an active Owner")

    if "store_ids" in changes and body.store_ids is not None:
        _check_stores(db, ctx, body.store_ids)
        _set_stores(db, user.id, body.store_ids)
    if body.password is not None:
        user.password_hash = hash_password(body.password)
    for field in ("full_name", "role_id", "is_active"):
        if field in changes and changes[field] is not None:
            setattr(user, field, changes[field])
    if body.password is not None or deactivating:
        db.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=func.now())
        )
    db.flush()
    after = _out(db, user).model_dump(mode="json")
    if body.password is not None:
        after["password_changed"] = True  # never log the password or its hash
    record_audit(
        db,
        business_id=ctx.business_id,
        user_id=ctx.user.id,
        action="user.updated",
        entity_type="user",
        entity_id=user.id,
        before=before,
        after=after,
    )
    db.commit()
    return _out(db, user)
