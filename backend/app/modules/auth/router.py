from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, get_auth
from app.core.config import get_settings
from app.db.session import get_db
from app.modules.auth import service
from app.modules.auth.schemas import LoginRequest, MeResponse, TokenResponse

router = APIRouter(prefix="/auth", tags=["auth"])
COOKIE = "refresh_token"


def _set_cookie(response: Response, raw: str) -> None:
    s = get_settings()
    response.set_cookie(
        COOKIE,
        raw,
        max_age=s.refresh_token_days * 86400,
        httponly=True,
        secure=s.cookie_secure,
        samesite="lax",
        path="/auth",
    )


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, response: Response, db: Session = Depends(get_db)) -> TokenResponse:
    try:
        access, raw = service.login(db, body.email, body.password)
    except service.AuthError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password") from None
    _set_cookie(response, raw)
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
        access, raw = service.refresh(db, refresh_token)
    except service.AuthError:
        response.delete_cookie(COOKIE, path="/auth")
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired") from None
    _set_cookie(response, raw)
    return TokenResponse(access_token=access)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    response: Response,
    db: Session = Depends(get_db),
    refresh_token: str | None = Cookie(default=None),
) -> None:
    if refresh_token:
        service.logout(db, refresh_token)
    response.delete_cookie(COOKIE, path="/auth")


@router.get("/me", response_model=MeResponse)
def me(ctx: AuthContext = Depends(get_auth)) -> MeResponse:
    return MeResponse(
        id=ctx.user.id,
        business_id=ctx.business_id,
        email=ctx.user.email,
        full_name=ctx.user.full_name,
        role=ctx.role.name,
        permissions=sorted(ctx.permissions),
        store_ids=sorted(ctx.store_ids),
    )
