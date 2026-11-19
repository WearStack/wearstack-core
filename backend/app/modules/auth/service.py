import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import (
    create_access_token,
    hash_refresh_token,
    new_refresh_token,
    verify_password,
)
from app.models import RefreshToken, User


class AuthError(Exception):
    pass


def _issue(db: Session, user: User) -> tuple[str, str]:
    raw, hashed = new_refresh_token()
    expires = datetime.now(UTC) + timedelta(days=get_settings().refresh_token_days)
    db.add(RefreshToken(user_id=user.id, token_hash=hashed, expires_at=expires))
    return create_access_token(user.id, user.business_id), raw


def login(db: Session, email: str, password: str) -> tuple[str, str]:
    """Returns (access_token, raw_refresh_token). Same error for unknown user and bad password."""
    user = db.scalars(select(User).where(User.email == email.lower())).first()
    ok = verify_password(password, user.password_hash if user else None)
    if user is None or not ok or not user.is_active:
        raise AuthError
    tokens = _issue(db, user)
    db.commit()
    return tokens


def _revoke_all(db: Session, user_id: uuid.UUID) -> None:
    db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )


def refresh(db: Session, raw: str) -> tuple[str, str]:
    """Rotates the refresh token. Re-use of a revoked token revokes the whole token family."""
    row = db.scalars(
        select(RefreshToken).where(RefreshToken.token_hash == hash_refresh_token(raw))
    ).first()
    if row is None:
        raise AuthError
    if row.revoked_at is not None:
        _revoke_all(db, row.user_id)
        db.commit()
        raise AuthError
    user = db.get(User, row.user_id)
    if row.expires_at < datetime.now(UTC) or user is None or not user.is_active:
        raise AuthError
    row.revoked_at = datetime.now(UTC)
    tokens = _issue(db, user)
    db.commit()
    return tokens


def logout(db: Session, raw: str) -> None:
    row = db.scalars(
        select(RefreshToken).where(RefreshToken.token_hash == hash_refresh_token(raw))
    ).first()
    if row is not None and row.revoked_at is None:
        row.revoked_at = datetime.now(UTC)
        db.commit()
