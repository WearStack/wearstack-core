from typing import Any

from fastapi.testclient import TestClient

from tests.conftest import OWNER, SETUP_BODY, login


def test_setup_creates_business_and_locks(client: TestClient) -> None:
    assert client.post("/setup", json=SETUP_BODY).status_code == 201
    again = client.post("/setup", json=SETUP_BODY)
    assert again.status_code == 409


def test_setup_status_reflects_completion(client: TestClient) -> None:
    assert client.get("/setup/status").json() == {"setup_required": True}
    client.post("/setup", json=SETUP_BODY)
    assert client.get("/setup/status").json() == {"setup_required": False}


def test_setup_validates_input(client: TestClient) -> None:
    bad = {**SETUP_BODY, "owner_password": "short", "state_code": "ABC"}
    assert client.post("/setup", json=bad).status_code == 422


def test_login_and_me(client: TestClient, owner: dict[str, str]) -> None:
    me = client.get("/auth/me", headers=owner).json()
    assert me["email"] == OWNER["email"]
    assert me["role"] == "Owner"
    assert "user:write" in me["permissions"]
    assert len(me["store_ids"]) == 1


def test_login_email_is_case_insensitive(client: TestClient, setup_ids: dict[str, str]) -> None:
    login(client, OWNER["email"].upper(), OWNER["password"])


def test_bad_credentials_are_indistinguishable(
    client: TestClient, setup_ids: dict[str, str]
) -> None:
    wrong_pw = client.post("/auth/login", json={"email": OWNER["email"], "password": "nope-nope-1"})
    no_user = client.post("/auth/login", json={"email": "x@example.com", "password": "nope-nope-1"})
    assert wrong_pw.status_code == no_user.status_code == 401
    assert wrong_pw.json() == no_user.json()


def test_protected_routes_need_a_valid_token(client: TestClient, setup_ids: dict[str, str]) -> None:
    assert client.get("/auth/me").status_code == 401
    assert client.get("/auth/me", headers={"Authorization": "Bearer garbage"}).status_code == 401


def _refresh_with(client: TestClient, token: str) -> int:
    client.cookies.clear()
    client.cookies.set("refresh_token", token, path="/auth")
    return client.post("/auth/refresh").status_code


def _current_token(client: TestClient) -> str:
    return [c.value for c in client.cookies.jar if c.name == "refresh_token" and c.value][-1]


def test_refresh_rotates_and_reuse_revokes_family(
    client: TestClient, setup_ids: dict[str, str]
) -> None:
    client.post("/auth/login", json=OWNER)
    first = _current_token(client)

    assert _refresh_with(client, first) == 200
    second = _current_token(client)
    assert second != first

    # Replaying the already-rotated token is treated as theft...
    assert _refresh_with(client, first) == 401
    # ...so the newest token is revoked too.
    assert _refresh_with(client, second) == 401


def test_logout_revokes_refresh_token(client: TestClient, setup_ids: dict[str, str]) -> None:
    client.post("/auth/login", json=OWNER)
    stale = _current_token(client)
    assert client.post("/auth/logout").status_code == 204
    assert _refresh_with(client, stale) == 401


def test_refresh_without_cookie_is_401(client: TestClient) -> None:
    assert client.post("/auth/refresh").status_code == 401


def test_api_docs_are_hidden_outside_development(monkeypatch: Any) -> None:
    from app.core.config import get_settings
    from app.main import create_app

    with TestClient(create_app()) as dev:
        assert dev.get("/openapi.json").status_code == 200  # tests run as development
    monkeypatch.setattr(get_settings(), "environment", "production")
    monkeypatch.setattr(get_settings(), "jwt_secret", "a-long-random-production-secret-value")
    with TestClient(create_app()) as prod:
        for path in ("/docs", "/redoc", "/openapi.json"):
            assert prod.get(path).status_code == 404, path
        assert prod.get("/health").status_code == 200
