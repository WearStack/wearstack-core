import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.permissions import DEFAULT_ROLES, OWNER_ROLE, PERMISSIONS
from app.models import Permission, Role, RolePermission, Store, User, UserStoreAccess


def sync_permissions(db: Session) -> dict[str, Permission]:
    """Idempotently makes the permissions table match the catalogue."""
    existing = {p.code: p for p in db.scalars(select(Permission))}
    for code, description in PERMISSIONS.items():
        if code not in existing:
            existing[code] = Permission(code=code, description=description)
            db.add(existing[code])
        elif existing[code].description != description:
            existing[code].description = description
    db.flush()
    return existing


def create_default_roles(db: Session, business_id: uuid.UUID) -> dict[str, Role]:
    perms = sync_permissions(db)
    roles: dict[str, Role] = {}
    for name, codes in DEFAULT_ROLES.items():
        role = Role(business_id=business_id, name=name, is_system=True)
        db.add(role)
        db.flush()
        db.add_all(
            RolePermission(role_id=role.id, permission_id=perms[c].id) for c in sorted(codes)
        )
        roles[name] = role
    return roles


def permission_codes(db: Session, role_id: uuid.UUID) -> set[str]:
    stmt = (
        select(Permission.code)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .where(RolePermission.role_id == role_id)
    )
    return set(db.scalars(stmt))


def accessible_store_ids(db: Session, user: User, role: Role) -> set[uuid.UUID]:
    """Owners see every store in the business; everyone else only their assigned stores."""
    if role.is_system and role.name == OWNER_ROLE:
        return set(db.scalars(select(Store.id).where(Store.business_id == user.business_id)))
    return set(
        db.scalars(select(UserStoreAccess.store_id).where(UserStoreAccess.user_id == user.id))
    )
