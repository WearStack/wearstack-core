import uuid
from collections.abc import Callable
from dataclasses import dataclass

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.security import decode_access_token
from app.db.session import get_db
from app.models import Role, User
from app.services.rbac import accessible_store_ids, permission_codes

_bearer = HTTPBearer(auto_error=False)


@dataclass
class AuthContext:
    user: User
    role: Role
    permissions: set[str]
    store_ids: set[uuid.UUID]

    @property
    def business_id(self) -> uuid.UUID:
        return self.user.business_id

    def require_store(self, store_id: uuid.UUID) -> None:
        if store_id not in self.store_ids:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "No access to this store")


def get_auth(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> AuthContext:
    unauthorized = HTTPException(
        status.HTTP_401_UNAUTHORIZED, "Not authenticated", headers={"WWW-Authenticate": "Bearer"}
    )
    if creds is None:
        raise unauthorized
    try:
        claims = decode_access_token(creds.credentials)
        user = db.get(User, uuid.UUID(claims["sub"]))
    except (jwt.PyJWTError, KeyError, ValueError):
        raise unauthorized from None
    if user is None or not user.is_active or str(user.business_id) != claims.get("biz"):
        raise unauthorized
    role = db.get(Role, user.role_id)
    assert role is not None
    return AuthContext(
        user=user,
        role=role,
        permissions=permission_codes(db, role.id),
        store_ids=accessible_store_ids(db, user, role),
    )


def require_permission(code: str) -> Callable[[AuthContext], AuthContext]:
    def checker(ctx: AuthContext = Depends(get_auth)) -> AuthContext:
        if code not in ctx.permissions:
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Missing permission: {code}")
        return ctx

    return checker
