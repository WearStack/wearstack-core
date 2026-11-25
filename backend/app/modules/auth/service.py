import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import (
    create_access_token,
    hash_password,
    hash_refresh_token,
    new_refresh_token,
    verify_password,
)
from app.models import RefreshToken, User


class AuthError(Exception):
    pass


def _issue(db: Session, user: User, persistent: bool) -> tuple[str, str]:
    raw, hashed = new_refresh_token()
    s = get_settings()
    lifetime = (
        timedelta(days=s.refresh_token_days)
        if persistent
        else timedelta(hours=s.session_token_hours)
    )
    db.add(
        RefreshToken(
            user_id=user.id,
            token_hash=hashed,
            expires_at=datetime.now(UTC) + lifetime,
            persistent=persistent,
        )
    )
    return create_access_token(user.id, user.business_id), raw


def login(db: Session, email: str, password: str, remember: bool) -> tuple[str, str]:
    """Returns (access_token, raw_refresh_token). Same error for unknown user and bad password."""
    user = db.scalars(select(User).where(User.email == email.lower())).first()
    ok = verify_password(password, user.password_hash if user else None)
    if user is None or not ok or not user.is_active:
        raise AuthError
    tokens = _issue(db, user, remember)
    user.last_login_at = datetime.now(UTC)
    db.commit()
    return tokens


MIN_PASSWORD = 10


def password_problem(new: str, email: str) -> str | None:
    """Why a chosen password is not acceptable, or None."""
    if len(new) < MIN_PASSWORD:
        return f"Use at least {MIN_PASSWORD} characters"
    if len(new) > 128:
        return "Use at most 128 characters"
    if new.lower() in (email.lower(), email.split("@")[0].lower()):
        return "The password must not be your email address"
    return None


def end_all_sessions(db: Session, user: User) -> None:
    """Signs the user out everywhere, immediately: their refresh tokens stop working, and access
    tokens already issued are refused from now on (see tokens_valid_after in the auth check)."""
    _revoke_all(db, user.id)
    user.tokens_valid_after = datetime.now(UTC)


def change_own_password(
    db: Session, user: User, current: str, new: str, keep_signed_in_persistently: bool
) -> tuple[str, str]:
    """The person replaces their own password. All their other sessions end; this one continues
    on a fresh token pair. Returns (access_token, raw_refresh_token)."""
    if not verify_password(current, user.password_hash):
        raise AuthError
    user.password_hash = hash_password(new)
    user.must_change_password = False
    end_all_sessions(db, user)
    db.flush()
    tokens = _issue(db, user, keep_signed_in_persistently)
    db.commit()
    return tokens


def _revoke_all(db: Session, user_id: uuid.UUID) -> None:
    db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )


def refresh(db: Session, raw: str) -> tuple[str, str, bool]:
    """Rotates the refresh token, keeping its "remember me" choice.

    Returns (access, raw, persistent). Re-use of a revoked token revokes the whole token family."""
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
    access, new_raw = _issue(db, user, row.persistent)
    db.commit()
    return access, new_raw, row.persistent


def logout(db: Session, raw: str) -> None:
    row = db.scalars(
        select(RefreshToken).where(RefreshToken.token_hash == hash_refresh_token(raw))
    ).first()
    if row is not None and row.revoked_at is None:
        row.revoked_at = datetime.now(UTC)
        db.commit()


def is_persistent(db: Session, raw: str | None) -> bool:
    """Whether the caller's current session was a "remember me" one (a new one inherits it)."""
    if not raw:
        return False
    row = db.scalars(
        select(RefreshToken).where(RefreshToken.token_hash == hash_refresh_token(raw))
    ).first()
    return bool(row and row.persistent)
