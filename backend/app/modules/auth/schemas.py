import uuid

from pydantic import BaseModel, EmailStr


class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    # Ticked on the login page: stay signed in for days. Otherwise the sign-in ends when the
    # browser closes (important on a shared counter PC).
    remember: bool = False


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class MeResponse(BaseModel):
    id: uuid.UUID
    business_id: uuid.UUID
    email: str
    full_name: str
    role: str
    permissions: list[str]
    store_ids: list[uuid.UUID]
    # True until the person has replaced a temporary password set by an administrator.
    must_change_password: bool = False


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class MyStore(BaseModel):
    """What any signed-in user may know about a store they work in."""

    id: uuid.UUID
    code: str
    name: str
    address: str | None
    state_code: str
    is_active: bool

    model_config = {"from_attributes": True}
