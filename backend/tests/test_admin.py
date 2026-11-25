import time
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.conftest import login

TEMP = "temporary-pass-1"


@pytest.fixture
def newbie(client: TestClient, owner: dict[str, str], roles: dict[str, str]) -> dict[str, Any]:
    """A user just created by the owner: they have only a temporary password."""
    res = client.post(
        "/users",
        headers=owner,
        json={
            "email": "newbie@example.com",
            "full_name": "New Person",
            "password": TEMP,
            "role_id": roles["Cashier"],
            "store_ids": [],
        },
    )
    assert res.status_code == 201, res.text
    return {"id": res.json()["id"], "email": "newbie@example.com"}


def raw_login(
    email: str, password: str, remember: bool = False
) -> tuple[TestClient, dict[str, str]]:
    c = TestClient(app)
    res = c.post("/auth/login", json={"email": email, "password": password, "remember": remember})
    assert res.status_code == 200, res.text
    return c, {"Authorization": f"Bearer {res.json()['access_token']}"}


# ---- the temporary password must be replaced first ----
def test_a_new_user_must_change_their_temporary_password_before_anything_else(
    client: TestClient, newbie: dict[str, Any]
) -> None:
    c, headers = raw_login(newbie["email"], TEMP)
    me = c.get("/auth/me", headers=headers)
    assert me.status_code == 200 and me.json()["must_change_password"] is True
    for path in ("/auth/stores", "/products", "/stores", "/customers", "/reports/overview"):
        res = c.get(path, headers=headers)
        assert res.status_code == 403, path
        assert "Change your temporary password" in res.json()["detail"]
    sale = c.post("/sales", headers=headers, json={})
    assert sale.status_code in (403, 422) and sale.status_code != 201


def test_changing_the_password_unlocks_the_account_and_retires_the_old_password(
    client: TestClient, newbie: dict[str, Any]
) -> None:
    c, headers = raw_login(newbie["email"], TEMP)
    new = "my-own-password-9"
    res = c.post(
        "/auth/change-password",
        headers=headers,
        json={"current_password": TEMP, "new_password": new},
    )
    assert res.status_code == 200, res.text
    fresh = {"Authorization": f"Bearer {res.json()['access_token']}"}
    assert c.get("/auth/me", headers=fresh).json()["must_change_password"] is False
    assert c.get("/auth/stores", headers=fresh).status_code == 200  # works now
    assert (
        TestClient(app)
        .post("/auth/login", json={"email": newbie["email"], "password": TEMP})
        .status_code
        == 401
    )
    assert (
        TestClient(app)
        .post("/auth/login", json={"email": newbie["email"], "password": new})
        .status_code
        == 200
    )
    assert c.post("/auth/refresh").status_code == 200  # this session carries on


def test_password_rules(client: TestClient, newbie: dict[str, Any]) -> None:
    _, h = raw_login(newbie["email"], TEMP)
    c = TestClient(app)

    def attempt(current: str, new: str) -> Any:
        return c.post(
            "/auth/change-password",
            headers=h,
            json={"current_password": current, "new_password": new},
        )

    assert attempt("wrong-current-password", "valid-new-password-1").status_code == 400
    assert attempt(TEMP, "short").status_code == 422
    assert attempt(TEMP, TEMP).status_code == 422  # must differ
    assert attempt(TEMP, newbie["email"]).status_code == 422  # not the email
    assert attempt(TEMP, "newbie").status_code == 422  # nor its first part
    assert attempt(TEMP, "x" * 129).status_code == 422
    assert c.get("/auth/me", headers=h).json()["must_change_password"] is True  # nothing changed


def test_change_password_requires_signing_in(client: TestClient) -> None:
    res = client.post(
        "/auth/change-password", json={"current_password": "a", "new_password": "b" * 12}
    )
    assert res.status_code == 401


def test_the_remember_me_choice_survives_a_password_change(
    client: TestClient, newbie: dict[str, Any]
) -> None:
    for remember in (True, False):
        c, h = raw_login(newbie["email"], TEMP if remember else "kept-password-777", remember)
        new = "kept-password-777" if remember else "another-password-888"
        res = c.post(
            "/auth/change-password",
            headers=h,
            json={
                "current_password": TEMP if remember else "kept-password-777",
                "new_password": new,
            },
        )
        cookie = next(v for k, v in res.headers.multi_items() if k == "set-cookie")
        assert ("Max-Age" in cookie) is remember
        # the next round starts from the password just chosen
        if remember:
            continue


def test_the_admins_reset_is_temporary_and_ends_open_sessions_immediately(
    client: TestClient, owner: dict[str, str], newbie: dict[str, Any]
) -> None:
    c, h = raw_login(newbie["email"], TEMP)
    c.post(
        "/auth/change-password",
        headers=h,
        json={"current_password": TEMP, "new_password": "chosen-password-1"},
    )
    c2, h2 = raw_login(newbie["email"], "chosen-password-1")
    assert c2.get("/auth/stores", headers=h2).status_code == 200
    time.sleep(1.1)  # tokens are timestamped to the second

    res = client.patch(
        f"/users/{newbie['id']}", headers=owner, json={"password": "admin-reset-pass-1"}
    )
    assert res.status_code == 200 and res.json()["must_change_password"] is True
    assert c2.get("/auth/stores", headers=h2).status_code == 401  # the open session is over now
    assert c2.post("/auth/refresh").status_code == 401  # and cannot be renewed
    c3, h3 = raw_login(newbie["email"], "admin-reset-pass-1")
    assert c3.get("/auth/stores", headers=h3).status_code == 403  # temporary again: must change


def test_sign_out_everywhere_ends_sessions_at_once_but_allows_signing_in_again(
    client: TestClient, owner: dict[str, str], make_user: Any
) -> None:
    make_user("Cashier", "cash@example.com")
    sessions = [raw_login("cash@example.com", "user-password-1") for _ in range(2)]  # two devices
    for c, h in sessions:
        assert c.get("/auth/stores", headers=h).status_code == 200
    uid = client.get("/users", headers=owner).json()
    uid = next(u["id"] for u in uid if u["email"] == "cash@example.com")
    time.sleep(1.1)
    assert client.post(f"/users/{uid}/sign-out", headers=owner).status_code == 204
    for c, h in sessions:
        assert c.get("/auth/stores", headers=h).status_code == 401
        assert c.post("/auth/refresh").status_code == 401
    c, h = raw_login("cash@example.com", "user-password-1")  # not locked out
    assert c.get("/auth/stores", headers=h).status_code == 200
    logs = client.get(
        "/audit-logs", headers=owner, params={"action_prefix": "user.signed_out"}
    ).json()
    assert len(logs) == 1 and logs[0]["after"] == {"email": "cash@example.com"}


def test_sign_out_needs_permission_and_respects_owner_protection(
    client: TestClient, owner: dict[str, str], make_user: Any
) -> None:
    import uuid

    cashier = make_user("Cashier", "cash@example.com")
    manager = make_user("Manager", "mgr@example.com")  # can read users, cannot write them
    owner_id = client.get("/auth/me", headers=owner).json()["id"]
    cash_id = client.get("/auth/me", headers=cashier).json()["id"]
    assert client.post(f"/users/{cash_id}/sign-out", headers=cashier).status_code == 403
    assert client.post(f"/users/{cash_id}/sign-out", headers=manager).status_code == 403
    assert client.post(f"/users/{cash_id}/sign-out").status_code == 401
    assert client.post(f"/users/{uuid.uuid4()}/sign-out", headers=owner).status_code == 404
    # A user admin who is not an Owner cannot sign out an Owner.
    client.post(
        "/roles",
        headers=owner,
        json={"name": "UserAdmin", "permissions": ["user:write", "user:read"]},
    )
    role = next(
        r["id"] for r in client.get("/roles", headers=owner).json() if r["name"] == "UserAdmin"
    )
    client.post(
        "/users",
        headers=owner,
        json={
            "email": "ua@example.com",
            "full_name": "UA",
            "password": "user-password-1",
            "role_id": role,
        },
    )
    ua = login(client, "ua@example.com", "user-password-1")
    assert client.post(f"/users/{owner_id}/sign-out", headers=ua).status_code == 403
    assert client.post(f"/users/{cash_id}/sign-out", headers=ua).status_code == 204


def test_deactivating_a_user_also_ends_their_open_sessions(
    client: TestClient, owner: dict[str, str], make_user: Any
) -> None:
    make_user("Cashier", "cash@example.com")
    c, h = raw_login("cash@example.com", "user-password-1")
    uid = next(
        u["id"]
        for u in client.get("/users", headers=owner).json()
        if u["email"] == "cash@example.com"
    )
    client.patch(f"/users/{uid}", headers=owner, json={"is_active": False})
    assert c.get("/auth/stores", headers=h).status_code == 401
    assert c.post("/auth/refresh").status_code == 401


# ---- what the admin page shows ----
def test_users_list_shows_last_sign_in_and_pending_password_change(
    client: TestClient, owner: dict[str, str], newbie: dict[str, Any]
) -> None:
    def row() -> dict[str, Any]:
        return next(
            u for u in client.get("/users", headers=owner).json() if u["email"] == newbie["email"]
        )

    before = row()
    assert before["last_login_at"] is None and before["must_change_password"] is True
    raw_login(newbie["email"], TEMP)
    after = row()
    assert after["last_login_at"] is not None and after["must_change_password"] is True
    # The owner (not forced, and signed in during setup) shows a sign-in time too.
    me = next(
        u for u in client.get("/users", headers=owner).json() if u["email"] == "owner@example.com"
    )
    assert me["must_change_password"] is False and me["last_login_at"] is not None


def test_activity_log_names_the_person_and_can_be_filtered(
    client: TestClient, owner: dict[str, str], newbie: dict[str, Any], make_user: Any
) -> None:
    client.post("/stores", headers=owner, json={"code": "B2", "name": "B2", "state_code": "27"})
    logs = client.get("/audit-logs", headers=owner).json()
    created = next(
        e for e in logs if e["action"] == "user.created" and e["after"]["email"] == newbie["email"]
    )
    assert created["user_name"] == "Olive Owner"  # shown by name, not an id
    users_only = client.get("/audit-logs", headers=owner, params={"action_prefix": "user."}).json()
    assert users_only and all(e["action"].startswith("user.") for e in users_only)
    owner_id = client.get("/auth/me", headers=owner).json()["id"]
    by_owner = client.get("/audit-logs", headers=owner, params={"user_id": owner_id}).json()
    assert by_owner and all(e["user_id"] == owner_id for e in by_owner)
    # Wildcard characters are plain text, not patterns.
    assert client.get("/audit-logs", headers=owner, params={"action_prefix": "%"}).json() == []
    assert client.get("/audit-logs", headers=owner, params={"action_prefix": "_"}).json() == []
    # Only those allowed to see the audit log may read it.
    cashier = make_user("Cashier", "cash@example.com")
    assert client.get("/audit-logs", headers=cashier).status_code == 403


def test_password_rules_apply_when_an_administrator_sets_one(
    client: TestClient, owner: dict[str, str], newbie: dict[str, Any], roles: dict[str, str]
) -> None:
    body = {"email": "other@example.com", "full_name": "O", "role_id": roles["Cashier"]}
    assert (
        client.post(
            "/users", headers=owner, json={**body, "password": "other@example.com"}
        ).status_code
        == 422
    )
    assert (
        client.post("/users", headers=owner, json={**body, "password": "short"}).status_code == 422
    )
    res = client.patch(f"/users/{newbie['id']}", headers=owner, json={"password": newbie["email"]})
    assert res.status_code == 422 and "email" in res.json()["detail"]


def test_the_owner_created_at_setup_is_not_forced_to_change_a_password(
    client: TestClient, owner: dict[str, str]
) -> None:
    assert client.get("/auth/me", headers=owner).json()["must_change_password"] is False
