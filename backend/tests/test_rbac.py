from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.db.session import SessionLocal
from app.models import AuditLog, Business, Role, Store, User
from app.services.rbac import create_default_roles
from tests.conftest import login


def test_cashier_is_denied_admin_routes(client: TestClient, make_user: Any) -> None:
    cashier = make_user("Cashier", "cash@example.com")
    for method, path in [
        ("get", "/users"),
        ("get", "/roles"),
        ("get", "/stores"),
        ("get", "/audit-logs"),
        ("post", "/stores"),
    ]:
        res = getattr(client, method)(path, headers=cashier)
        assert res.status_code == 403, (method, path, res.status_code)
        assert "Missing permission" in res.json()["detail"]


def test_manager_can_read_but_not_write_users(client: TestClient, make_user: Any) -> None:
    manager = make_user("Manager", "mgr@example.com")
    assert client.get("/users", headers=manager).status_code == 200
    body = {
        "email": "x@example.com",
        "full_name": "X",
        "password": "password-123",
        "role_id": "00000000-0000-0000-0000-000000000000",
    }
    assert client.post("/users", headers=manager, json=body).status_code == 403


def test_store_list_is_scoped_to_assigned_stores(
    client: TestClient, owner: dict[str, str], make_user: Any
) -> None:
    second = client.post(
        "/stores", headers=owner, json={"code": "B2", "name": "Branch 2", "state_code": "27"}
    ).json()
    main_id = next(
        s["id"] for s in client.get("/stores", headers=owner).json() if s["code"] == "MAIN"
    )
    mgr = make_user("Manager", "mgr@example.com", store_ids=[second["id"]])

    visible = {s["id"] for s in client.get("/stores", headers=mgr).json()}
    assert visible == {second["id"]}
    assert main_id not in visible
    # Owner sees every store, including ones created later.
    assert len(client.get("/stores", headers=owner).json()) == 2


def test_cannot_touch_a_store_you_lack_access_to(
    client: TestClient, owner: dict[str, str], make_user: Any
) -> None:
    owner_store = client.get("/stores", headers=owner).json()[0]["id"]
    other = client.post(
        "/stores", headers=owner, json={"code": "B2", "name": "Branch 2", "state_code": "27"}
    ).json()
    # A user with store:write via a custom role, but assigned only to the other store.
    role = client.post(
        "/roles", headers=owner, json={"name": "StoreAdmin", "permissions": ["store:write"]}
    ).json()
    client.post(
        "/users",
        headers=owner,
        json={
            "email": "sa@example.com",
            "full_name": "SA",
            "password": "user-password-1",
            "role_id": role["id"],
            "store_ids": [other["id"]],
        },
    )
    sa = login(client, "sa@example.com", "user-password-1")

    assert (
        client.patch(f"/stores/{owner_store}", headers=sa, json={"name": "Hacked"}).status_code
        == 403
    )
    assert (
        client.patch(f"/stores/{other['id']}", headers=sa, json={"name": "Renamed"}).status_code
        == 200
    )


def test_duplicate_store_code_conflicts(client: TestClient, owner: dict[str, str]) -> None:
    res = client.post(
        "/stores", headers=owner, json={"code": "MAIN", "name": "Dup", "state_code": "27"}
    )
    assert res.status_code == 409


def test_only_owner_can_assign_owner_role(
    client: TestClient, owner: dict[str, str], roles: dict[str, str]
) -> None:
    role = client.post(
        "/roles",
        headers=owner,
        json={"name": "UserAdmin", "permissions": ["user:write", "user:read"]},
    ).json()
    client.post(
        "/users",
        headers=owner,
        json={
            "email": "ua@example.com",
            "full_name": "UA",
            "password": "user-password-1",
            "role_id": role["id"],
        },
    )
    ua = login(client, "ua@example.com", "user-password-1")

    res = client.post(
        "/users",
        headers=ua,
        json={
            "email": "sneaky@example.com",
            "full_name": "S",
            "password": "user-password-1",
            "role_id": roles["Owner"],
        },
    )
    assert res.status_code == 403


def test_cannot_grant_permissions_you_do_not_hold(
    client: TestClient, owner: dict[str, str]
) -> None:
    client.post(
        "/roles",
        headers=owner,
        json={"name": "RoleAdmin", "permissions": ["role:write", "role:read"]},
    )
    role_id = next(
        r["id"] for r in client.get("/roles", headers=owner).json() if r["name"] == "RoleAdmin"
    )
    client.post(
        "/users",
        headers=owner,
        json={
            "email": "ra@example.com",
            "full_name": "RA",
            "password": "user-password-1",
            "role_id": role_id,
        },
    )
    ra = login(client, "ra@example.com", "user-password-1")

    res = client.post(
        "/roles", headers=ra, json={"name": "Escalated", "permissions": ["audit:read"]}
    )
    assert res.status_code == 403


def test_system_roles_are_immutable(
    client: TestClient, owner: dict[str, str], roles: dict[str, str]
) -> None:
    assert (
        client.patch(f"/roles/{roles['Cashier']}", headers=owner, json={"name": "X"}).status_code
        == 403
    )
    assert client.delete(f"/roles/{roles['Cashier']}", headers=owner).status_code == 403


def test_role_in_use_cannot_be_deleted(client: TestClient, owner: dict[str, str]) -> None:
    role = client.post(
        "/roles", headers=owner, json={"name": "Temp", "permissions": ["sale:read"]}
    ).json()
    client.post(
        "/users",
        headers=owner,
        json={
            "email": "t@example.com",
            "full_name": "T",
            "password": "user-password-1",
            "role_id": role["id"],
        },
    )
    assert client.delete(f"/roles/{role['id']}", headers=owner).status_code == 409


def test_unknown_permission_rejected(client: TestClient, owner: dict[str, str]) -> None:
    res = client.post("/roles", headers=owner, json={"name": "Bad", "permissions": ["nope:nope"]})
    assert res.status_code == 422


def test_last_owner_is_protected(
    client: TestClient, owner: dict[str, str], roles: dict[str, str]
) -> None:
    me = client.get("/auth/me", headers=owner).json()
    assert (
        client.patch(f"/users/{me['id']}", headers=owner, json={"is_active": False}).status_code
        == 409
    )
    res = client.patch(f"/users/{me['id']}", headers=owner, json={"role_id": roles["Manager"]})
    assert res.status_code == 409


def test_deactivated_user_loses_access_immediately(
    client: TestClient, owner: dict[str, str], make_user: Any
) -> None:
    cashier = make_user("Cashier", "cash@example.com")
    uid = client.get("/auth/me", headers=cashier).json()["id"]
    assert (
        client.patch(f"/users/{uid}", headers=owner, json={"is_active": False}).status_code == 200
    )
    assert client.get("/auth/me", headers=cashier).status_code == 401
    res = client.post(
        "/auth/login", json={"email": "cash@example.com", "password": "user-password-1"}
    )
    assert res.status_code == 401


def test_duplicate_email_conflicts(
    client: TestClient, owner: dict[str, str], roles: dict[str, str]
) -> None:
    body = {
        "email": "dup@example.com",
        "full_name": "D",
        "password": "user-password-1",
        "role_id": roles["Cashier"],
    }
    assert client.post("/users", headers=owner, json=body).status_code == 201
    assert (
        client.post("/users", headers=owner, json={**body, "email": "DUP@example.com"}).status_code
        == 409
    )


def test_business_data_is_isolated(client: TestClient, owner: dict[str, str]) -> None:
    """A second business (inserted directly) must never appear in the first one's API."""
    with SessionLocal() as db:
        _make_other_business(db)
    assert {u["email"] for u in client.get("/users", headers=owner).json()} == {"owner@example.com"}
    assert {s["code"] for s in client.get("/stores", headers=owner).json()} == {"MAIN"}
    assert {r["name"] for r in client.get("/roles", headers=owner).json()} == {
        "Owner",
        "Manager",
        "Cashier",
    }
    other_user = _other_user_id()
    assert (
        client.patch(f"/users/{other_user}", headers=owner, json={"full_name": "x"}).status_code
        == 404
    )


def _make_other_business(db: Session) -> None:
    biz = Business(name="Other Co", state_code="29")
    db.add(biz)
    db.flush()
    roles = create_default_roles(db, biz.id)
    db.add(Store(business_id=biz.id, code="OTHER", name="Other", state_code="29"))
    db.add(
        User(
            business_id=biz.id,
            role_id=roles["Owner"].id,
            email="other@example.com",
            full_name="Other",
            password_hash=hash_password("other-password-1"),
        )
    )
    db.commit()


def _other_user_id() -> str:
    with SessionLocal() as db:
        return str(db.scalars(select(User.id).where(User.email == "other@example.com")).one())


def test_password_change_revokes_sessions_and_is_not_audited_in_clear(
    client: TestClient, owner: dict[str, str], make_user: Any
) -> None:
    make_user("Cashier", "cash@example.com")
    c2 = TestClient(client.app)
    c2.post("/auth/login", json={"email": "cash@example.com", "password": "user-password-1"})
    uid = next(
        u["id"]
        for u in client.get("/users", headers=owner).json()
        if u["email"] == "cash@example.com"
    )

    client.patch(f"/users/{uid}", headers=owner, json={"password": "brand-new-password"})
    assert c2.post("/auth/refresh").status_code == 401
    login(client, "cash@example.com", "brand-new-password")

    with SessionLocal() as db:
        rows = db.scalars(select(AuditLog).where(AuditLog.action == "user.updated")).all()
        dump = str([r.before for r in rows] + [r.after for r in rows])
    assert "brand-new-password" not in dump and "argon2" not in dump


def test_mutations_write_audit_rows(client: TestClient, owner: dict[str, str]) -> None:
    store = client.post(
        "/stores", headers=owner, json={"code": "B2", "name": "B2", "state_code": "27"}
    ).json()
    client.patch(f"/stores/{store['id']}", headers=owner, json={"name": "Renamed"})

    logs = client.get("/audit-logs", headers=owner, params={"entity_type": "store"}).json()
    actions = [entry["action"] for entry in logs]
    assert actions == ["store.updated", "store.created"]  # newest first
    updated = logs[0]
    assert updated["before"]["name"] == "B2" and updated["after"]["name"] == "Renamed"
    all_actions = {e["action"] for e in client.get("/audit-logs", headers=owner).json()}
    assert "setup.completed" in all_actions


def test_roles_have_expected_system_set(client: TestClient, owner: dict[str, str]) -> None:
    got = {r["name"]: r for r in client.get("/roles", headers=owner).json()}
    assert all(r["is_system"] for r in got.values())
    assert "user:write" not in got["Manager"]["permissions"]
    assert "sale:create" in got["Cashier"]["permissions"]
    with SessionLocal() as db:
        assert db.scalars(select(Role)).all()
