import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, require_permission
from app.core.permissions import PERMISSIONS
from app.db.session import get_db
from app.models import Permission, Role, RolePermission, User
from app.services.audit import record_audit
from app.services.rbac import permission_codes, sync_permissions

router = APIRouter(tags=["roles"])


class RoleIn(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    permissions: list[str]


class RoleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=50)
    permissions: list[str] | None = None


class RoleOut(BaseModel):
    id: uuid.UUID
    name: str
    is_system: bool
    permissions: list[str]


def _out(db: Session, role: Role) -> RoleOut:
    return RoleOut(
        id=role.id,
        name=role.name,
        is_system=role.is_system,
        permissions=sorted(permission_codes(db, role.id)),
    )


def _get(db: Session, ctx: AuthContext, role_id: uuid.UUID) -> Role:
    role = db.get(Role, role_id)
    if role is None or role.business_id != ctx.business_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Role not found")
    return role


def _check_grantable(ctx: AuthContext, codes: list[str]) -> None:
    unknown = set(codes) - set(PERMISSIONS)
    if unknown:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Unknown: {sorted(unknown)}")
    if ctx.role.is_system and ctx.role.name == "Owner":
        return
    if set(codes) - ctx.permissions:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Cannot grant permissions you do not hold")


def _set_permissions(db: Session, role: Role, codes: list[str]) -> None:
    perms = sync_permissions(db)
    db.execute(delete(RolePermission).where(RolePermission.role_id == role.id))
    db.add_all(RolePermission(role_id=role.id, permission_id=perms[c].id) for c in set(codes))
    db.flush()


@router.get("/permissions", response_model=dict[str, str])
def list_permissions(
    _: AuthContext = Depends(require_permission("role:read")), db: Session = Depends(get_db)
) -> dict[str, str]:
    return {p.code: p.description for p in db.scalars(select(Permission).order_by(Permission.code))}


@router.get("/roles", response_model=list[RoleOut])
def list_roles(
    ctx: AuthContext = Depends(require_permission("role:read")), db: Session = Depends(get_db)
) -> list[RoleOut]:
    roles = db.scalars(select(Role).where(Role.business_id == ctx.business_id).order_by(Role.name))
    return [_out(db, r) for r in roles]


@router.post("/roles", response_model=RoleOut, status_code=status.HTTP_201_CREATED)
def create_role(
    body: RoleIn,
    ctx: AuthContext = Depends(require_permission("role:write")),
    db: Session = Depends(get_db),
) -> RoleOut:
    _check_grantable(ctx, body.permissions)
    role = Role(business_id=ctx.business_id, name=body.name)
    db.add(role)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Role name already exists") from None
    _set_permissions(db, role, body.permissions)
    record_audit(
        db,
        business_id=ctx.business_id,
        user_id=ctx.user.id,
        action="role.created",
        entity_type="role",
        entity_id=role.id,
        after={"name": role.name, "permissions": sorted(set(body.permissions))},
    )
    db.commit()
    return _out(db, role)


@router.patch("/roles/{role_id}", response_model=RoleOut)
def update_role(
    role_id: uuid.UUID,
    body: RoleUpdate,
    ctx: AuthContext = Depends(require_permission("role:write")),
    db: Session = Depends(get_db),
) -> RoleOut:
    role = _get(db, ctx, role_id)
    if role.is_system:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "System roles cannot be modified")
    before = _out(db, role).model_dump(mode="json")
    if body.permissions is not None:
        _check_grantable(ctx, body.permissions)
        _set_permissions(db, role, body.permissions)
    if body.name is not None:
        role.name = body.name
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Role name already exists") from None
    record_audit(
        db,
        business_id=ctx.business_id,
        user_id=ctx.user.id,
        action="role.updated",
        entity_type="role",
        entity_id=role.id,
        before=before,
        after=_out(db, role).model_dump(mode="json"),
    )
    db.commit()
    return _out(db, role)


@router.delete("/roles/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_role(
    role_id: uuid.UUID,
    ctx: AuthContext = Depends(require_permission("role:write")),
    db: Session = Depends(get_db),
) -> None:
    role = _get(db, ctx, role_id)
    if role.is_system:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "System roles cannot be deleted")
    if db.scalar(select(func.count()).select_from(User).where(User.role_id == role.id)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Role is assigned to users")
    before = _out(db, role).model_dump(mode="json")
    db.delete(role)
    record_audit(
        db,
        business_id=ctx.business_id,
        user_id=ctx.user.id,
        action="role.deleted",
        entity_type="role",
        entity_id=role_id,
        before=before,
    )
    db.commit()
