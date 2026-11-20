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


def test_every_signed_in_user_can_list_their_own_stores(
    client: TestClient, owner: dict[str, str], make_user: Any
) -> None:
    main = client.get("/stores", headers=owner).json()[0]
    other = client.post(
        "/stores", headers=owner, json={"code": "B2", "name": "Branch", "state_code": "27"}
    ).json()
    cashier = make_user("Cashier", "cash@example.com", store_ids=[other["id"]])
    # The Cashier role has no store:read, so /stores is closed to them...
    assert client.get("/stores", headers=cashier).status_code == 403
    # ...but they can still learn which store they work in, and only that one.
    mine = client.get("/auth/stores", headers=cashier)
    assert mine.status_code == 200
    assert [s["id"] for s in mine.json()] == [other["id"]]
    assert set(mine.json()[0]) == {
        "id",
        "code",
        "name",
        "address",
        "state_code",
        "is_active",
    }  # no GSTIN
    assert [s["code"] for s in client.get("/auth/stores", headers=owner).json()] == [
        main["code"],
        "B2",
    ]
    assert client.get("/auth/stores").status_code == 401


# ---- "Remember me" ----
def _login_cookie(client: TestClient, remember: bool | None) -> str:
    body: dict[str, Any] = {**OWNER}
    if remember is not None:
        body["remember"] = remember
    res = client.post("/auth/login", json=body)
    assert res.status_code == 200, res.text
    return next(v for k, v in res.headers.multi_items() if k == "set-cookie")


def test_remembered_sessions_get_a_persistent_cookie_others_a_session_cookie(
    client: TestClient, setup_ids: dict[str, str]
) -> None:
    kept = _login_cookie(client, True)
    assert "Max-Age=1209600" in kept and "HttpOnly" in kept  # 14 days
    forgotten = _login_cookie(client, False)
    assert (
        "Max-Age" not in forgotten and "expires" not in forgotten.lower()
    )  # ends with the browser
    assert "HttpOnly" in forgotten
    # The safe default when a client does not say: do not persist.
    assert "Max-Age" not in _login_cookie(client, None)


def test_refresh_keeps_the_remember_choice_and_the_matching_lifetime(
    client: TestClient, setup_ids: dict[str, str]
) -> None:
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import text

    from app.db.session import engine

    for remember, hours in ((True, 14 * 24), (False, 12)):
        client.cookies.clear()
        _login_cookie(client, remember)
        res = client.post("/auth/refresh")  # rotates the token
        assert res.status_code == 200
        cookie = next(v for k, v in res.headers.multi_items() if k == "set-cookie")
        assert ("Max-Age" in cookie) is remember  # the choice survives rotation
        with engine.connect() as conn:
            persistent, expires = conn.execute(
                text(
                    "SELECT persistent, expires_at FROM refresh_tokens "
                    "ORDER BY created_at DESC LIMIT 1"
                )
            ).one()
        assert persistent is remember
        left = expires - datetime.now(UTC)
        assert timedelta(hours=hours) - timedelta(minutes=5) < left <= timedelta(hours=hours)


def test_a_session_that_was_not_remembered_expires_after_hours_not_days(
    client: TestClient, setup_ids: dict[str, str]
) -> None:
    from sqlalchemy import text

    from app.db.session import engine

    _login_cookie(client, False)
    with engine.begin() as conn:  # pretend 13 hours have passed (the limit is 12)
        conn.execute(text("UPDATE refresh_tokens SET expires_at = now() - interval '1 hour'"))
    assert client.post("/auth/refresh").status_code == 401
