import uuid
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.db.session import engine


def test_business_can_be_read_and_its_gstin_corrected(
    client: TestClient, owner: dict[str, str]
) -> None:
    b = client.get("/business", headers=owner).json()
    assert b["name"] == "Test Clothing Co" and b["gstin"] == "27AAPFU0939F1ZV"
    upd = client.patch(
        "/business", headers=owner, json={"gstin": "29ABCDE1234F1ZW", "legal_name": "Demo LLP"}
    )
    assert upd.status_code == 200 and upd.json()["gstin"] == "29ABCDE1234F1ZW"
    assert upd.json()["legal_name"] == "Demo LLP"
    again = client.patch("/business", headers=owner, json={"gstin": "27aapfu0939f1zv"})
    assert again.json()["gstin"] == "27AAPFU0939F1ZV"  # normalised to upper case


def test_business_gstin_must_be_valid_and_name_cannot_be_blanked(
    client: TestClient, owner: dict[str, str]
) -> None:
    assert (
        client.patch("/business", headers=owner, json={"gstin": "27AAPFU0939F1ZW"}).status_code
        == 422
    )
    assert client.patch("/business", headers=owner, json={"name": ""}).status_code == 422
    assert client.patch("/business", headers=owner, json={"name": None}).status_code == 422
    assert client.get("/business", headers=owner).json()["name"] == "Test Clothing Co"
    assert client.patch("/business", headers=owner, json={"gstin": None}).json()["gstin"] is None


def test_changes_are_audited_with_before_and_after(
    client: TestClient, owner: dict[str, str]
) -> None:
    client.patch("/business", headers=owner, json={"gstin": "29ABCDE1234F1ZW"})
    logs = client.get("/audit-logs", headers=owner, params={"entity_type": "business"}).json()
    assert logs[0]["action"] == "business.updated"
    assert logs[0]["before"] == {"gstin": "27AAPFU0939F1ZV"} and logs[0]["after"] == {
        "gstin": "29ABCDE1234F1ZW"
    }


def test_only_users_with_store_write_can_change_the_business(
    client: TestClient, make_user: Any
) -> None:
    manager = make_user("Manager", "mgr@example.com")  # can read stores, cannot write them
    cashier = make_user("Cashier", "cash@example.com")
    assert client.get("/business", headers=manager).status_code == 200
    assert client.patch("/business", headers=manager, json={"gstin": None}).status_code == 403
    assert client.get("/business", headers=cashier).status_code == 403
    assert client.patch("/business", headers=cashier, json={"name": "x"}).status_code == 403
    assert client.get("/business").status_code == 401


def test_stores_report_the_effective_gstin(
    client: TestClient, owner: dict[str, str], store_id: str
) -> None:
    s = client.get("/stores", headers=owner).json()[0]
    assert s["gstin"] == "27AAPFU0939F1ZV" and s["effective_gstin"] == "27AAPFU0939F1ZV"
    # A store with none of its own falls back to the business GSTIN...
    cleared = client.patch(f"/stores/{store_id}", headers=owner, json={"gstin": None}).json()
    assert cleared["gstin"] is None and cleared["effective_gstin"] == "27AAPFU0939F1ZV"
    # ...and its own GSTIN wins when it has one.
    own = client.patch(
        f"/stores/{store_id}", headers=owner, json={"gstin": "29ABCDE1234F1ZW"}
    ).json()
    assert own["effective_gstin"] == "29ABCDE1234F1ZW"
    # With neither, there is no seller GSTIN, which is what blocks billing.
    client.patch(f"/stores/{store_id}", headers=owner, json={"gstin": None})
    client.patch("/business", headers=owner, json={"gstin": None})
    assert client.get("/stores", headers=owner).json()[0]["effective_gstin"] is None


def test_billing_follows_the_effective_gstin(
    client: TestClient, owner: dict[str, str], store_id: str, make_product: Any
) -> None:
    rate = client.post(
        "/tax-rates",
        headers=owner,
        json={"name": "R5", "rate": "5", "effective_from": "2020-01-01"},
    ).json()["id"]
    v = make_product(price="100.00", tax_rate_id=rate)["variants"][0]["id"]
    client.post(
        "/inventory/movements",
        headers=owner,
        json={"store_id": store_id, "variant_id": v, "kind": "opening", "quantity": 9},
    )

    def sell() -> int:
        return client.post(
            "/sales",
            headers=owner,
            json={
                "idempotency_key": str(uuid.uuid4()),
                "store_id": store_id,
                "items": [{"variant_id": v, "quantity": 1}],
                "payments": [{"method": "cash", "amount": "100.00"}],
            },
        ).status_code

    client.patch(f"/stores/{store_id}", headers=owner, json={"gstin": None})
    assert sell() == 201  # the business GSTIN covers a store that has none
    client.patch("/business", headers=owner, json={"gstin": None})
    assert sell() == 409  # neither: blocked
    client.patch("/business", headers=owner, json={"gstin": "27AAPFU0939F1ZV"})
    assert sell() == 201  # fixing the business GSTIN unblocks billing
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM sales")).scalar() == 2
