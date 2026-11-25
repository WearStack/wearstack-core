from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, get_auth, get_auth_pending_ok
from app.core.config import get_settings
from app.db.session import get_db
from app.models import Store
from app.modules.auth import service
from app.modules.auth.schemas import (
    ChangePasswordRequest,
    LoginRequest,
    MeResponse,
    MyStore,
    TokenResponse,
)
from app.services.audit import record_audit

router = APIRouter(prefix="/auth", tags=["auth"])
COOKIE = "refresh_token"


def _set_cookie(response: Response, raw: str, persistent: bool) -> None:
    s = get_settings()
    response.set_cookie(
        COOKIE,
        raw,
        # No max-age makes it a session cookie: the browser drops it when it is closed.
        max_age=s.refresh_token_days * 86400 if persistent else None,
        httponly=True,
        secure=s.cookie_secure,
        samesite="lax",
        path=s.cookie_path,
    )


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, response: Response, db: Session = Depends(get_db)) -> TokenResponse:
    try:
        access, raw = service.login(db, body.email, body.password, body.remember)
    except service.AuthError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password") from None
    _set_cookie(response, raw, body.remember)
    return TokenResponse(access_token=access)


@router.post("/refresh", response_model=TokenResponse)
def refresh(
    response: Response,
    db: Session = Depends(get_db),
    refresh_token: str | None = Cookie(default=None),
) -> TokenResponse:
    try:
        if refresh_token is None:
            raise service.AuthError
        access, raw, persistent = service.refresh(db, refresh_token)
    except service.AuthError:
        response.delete_cookie(COOKIE, path=get_settings().cookie_path)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired") from None
    _set_cookie(response, raw, persistent)
    return TokenResponse(access_token=access)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    response: Response,
    db: Session = Depends(get_db),
    refresh_token: str | None = Cookie(default=None),
) -> None:
    if refresh_token:
        service.logout(db, refresh_token)
    response.delete_cookie(COOKIE, path=get_settings().cookie_path)


@router.get("/me", response_model=MeResponse)
def me(ctx: AuthContext = Depends(get_auth_pending_ok)) -> MeResponse:
    return MeResponse(
        id=ctx.user.id,
        business_id=ctx.business_id,
        email=ctx.user.email,
        full_name=ctx.user.full_name,
        role=ctx.role.name,
        permissions=sorted(ctx.permissions),
        store_ids=sorted(ctx.store_ids),
        must_change_password=ctx.user.must_change_password,
    )


@router.get("/stores", response_model=list[MyStore])
def my_stores(ctx: AuthContext = Depends(get_auth), db: Session = Depends(get_db)) -> list[Store]:
    """The stores this user works in, oldest first. Needs no permission: a cashier must be able to
    tell the POS which store they are selling from."""
    stmt = select(Store).where(Store.id.in_(ctx.store_ids)).order_by(Store.created_at, Store.code)
    return list(db.scalars(stmt))


@router.post("/change-password", response_model=TokenResponse)
def change_password(
    body: ChangePasswordRequest,
    response: Response,
    ctx: AuthContext = Depends(get_auth_pending_ok),
    db: Session = Depends(get_db),
    refresh_token: str | None = Cookie(default=None),
) -> TokenResponse:
    """Lets a person replace their own password (and is the only thing a person with a temporary
    password may do). Ends their other sessions and continues this one."""
    problem = service.password_problem(body.new_password, ctx.user.email)
    if problem:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, problem)
    if body.new_password == body.current_password:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Choose a password different from the current one",
        )
    persistent = service.is_persistent(db, refresh_token)
    try:
        access, raw = service.change_own_password(
            db, ctx.user, body.current_password, body.new_password, persistent
        )
    except service.AuthError:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Your current password is not correct"
        ) from None
    record_audit(
        db,
        business_id=ctx.business_id,
        user_id=ctx.user.id,
        action="user.password_changed",
        entity_type="user",
        entity_id=ctx.user.id,
        after={"self_service": True},
    )
    db.commit()
    _set_cookie(response, raw, persistent)
    return TokenResponse(access_token=access)
