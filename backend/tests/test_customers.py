from typing import Any

from fastapi.testclient import TestClient


def test_customer_crud_search_and_uniqueness(client: TestClient, owner: dict[str, str]) -> None:
    c = client.post("/customers", headers=owner, json={"name": "Asha Rao", "phone": "9876543210"})
    assert c.status_code == 201 and c.json()["marketing_consent"] is False
    assert (
        client.post(
            "/customers", headers=owner, json={"name": "Other", "phone": "9876543210"}
        ).status_code
        == 409
    )
    # Customers without a phone never collide with each other.
    assert client.post("/customers", headers=owner, json={"name": "No Phone 1"}).status_code == 201
    assert client.post("/customers", headers=owner, json={"name": "No Phone 2"}).status_code == 201
    assert [
        x["name"] for x in client.get("/customers", headers=owner, params={"q": "asha"}).json()
    ] == ["Asha Rao"]
    assert [
        x["name"] for x in client.get("/customers", headers=owner, params={"q": "98765"}).json()
    ] == ["Asha Rao"]
    upd = client.patch(
        f"/customers/{c.json()['id']}", headers=owner, json={"email": "asha@example.com"}
    )
    assert upd.json()["email"] == "asha@example.com"


def test_validation(client: TestClient, owner: dict[str, str]) -> None:
    for bad in (
        {"phone": "12ab"},
        {"gstin": "nope"},
        {"state_code": "7"},
        {"email": "x"},
        {"name": ""},
    ):
        assert (
            client.post("/customers", headers=owner, json={"name": "A", **bad}).status_code == 422
        )


def test_consent_is_recorded_with_a_timestamp_and_changes_are_audited(
    client: TestClient, owner: dict[str, str]
) -> None:
    c = client.post(
        "/customers", headers=owner, json={"name": "Ravi", "marketing_consent": True}
    ).json()
    assert c["marketing_consent"] is True
    client.patch(f"/customers/{c['id']}", headers=owner, json={"marketing_consent": False})
    logs = client.get("/audit-logs", headers=owner, params={"entity_type": "customer"}).json()
    assert [e["action"] for e in logs] == ["customer.updated", "customer.created"]
    assert (
        logs[0]["before"]["marketing_consent"] == "True"
        and logs[0]["after"]["marketing_consent"] == "False"
    )


def test_cashier_can_add_customers_but_viewer_cannot(
    client: TestClient, owner: dict[str, str], make_user: Any
) -> None:
    cashier = make_user("Cashier", "cash@example.com")
    assert client.post("/customers", headers=cashier, json={"name": "Walk In"}).status_code == 201
    client.post(
        "/roles", headers=owner, json={"name": "ReadOnly", "permissions": ["customer:read"]}
    )
    role = next(
        r["id"] for r in client.get("/roles", headers=owner).json() if r["name"] == "ReadOnly"
    )
    client.post(
        "/users",
        headers=owner,
        json={
            "email": "ro@example.com",
            "full_name": "RO",
            "password": "user-password-1",
            "role_id": role,
        },
    )
    from tests.conftest import login

    ro = login(client, "ro@example.com", "user-password-1")
    assert client.get("/customers", headers=ro).status_code == 200
    assert client.post("/customers", headers=ro, json={"name": "Nope"}).status_code == 403


def test_customers_are_business_scoped(client: TestClient, owner: dict[str, str]) -> None:
    from app.db.session import SessionLocal
    from app.models import Business, Customer

    with SessionLocal() as db:
        biz = Business(name="Other", state_code="29")
        db.add(biz)
        db.flush()
        other = Customer(business_id=biz.id, name="Secret", phone="9000000001")
        db.add(other)
        db.commit()
        other_id = str(other.id)
    assert client.get("/customers", headers=owner).json() == []
    assert (
        client.patch(f"/customers/{other_id}", headers=owner, json={"name": "x"}).status_code == 404
    )
    # The same phone number is allowed in a different business.
    assert (
        client.post(
            "/customers", headers=owner, json={"name": "Mine", "phone": "9000000001"}
        ).status_code
        == 201
    )
