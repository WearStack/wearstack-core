import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def supplier(client: TestClient, owner: dict[str, str]) -> dict[str, Any]:
    res = client.post(
        "/suppliers", headers=owner, json={"name": "Textile Traders", "gstin": "27ABCDE1234F1Z5"}
    )
    assert res.status_code == 201, res.text
    return res.json()  # type: ignore[no-any-return]


def bill(
    store: str, supplier_id: str, variants: list[str], number: str = "B-100"
) -> dict[str, Any]:
    return {
        "store_id": store,
        "supplier_id": supplier_id,
        "bill_number": number,
        "bill_date": "2026-11-01",
        "items": [{"variant_id": v, "quantity": 10, "unit_cost": "650.50"} for v in variants],
    }


def qty(client: TestClient, owner: dict[str, str], store: str, variant: str) -> int:
    rows = client.get("/inventory", headers=owner, params={"store_id": store}).json()
    return int(next(r["quantity"] for r in rows if r["variant_id"] == variant))


def test_supplier_crud_and_validation(
    client: TestClient, owner: dict[str, str], supplier: dict[str, Any]
) -> None:
    assert (
        client.post("/suppliers", headers=owner, json={"name": "Textile Traders"}).status_code
        == 409
    )
    assert (
        client.post("/suppliers", headers=owner, json={"name": "X", "gstin": "bad"}).status_code
        == 422
    )
    upd = client.patch(
        f"/suppliers/{supplier['id']}", headers=owner, json={"phone": "+919876543210"}
    )
    assert upd.json()["phone"] == "+919876543210"
    assert [s["name"] for s in client.get("/suppliers", headers=owner).json()] == [
        "Textile Traders"
    ]


def test_purchase_is_a_draft_until_received_then_adds_stock_and_cost(
    client: TestClient,
    owner: dict[str, str],
    store_id: str,
    supplier: dict[str, Any],
    make_product: Any,
) -> None:
    product = make_product(cost_price="100.00")
    a, b = (v["id"] for v in product["variants"])
    p = client.post("/purchases", headers=owner, json=bill(store_id, supplier["id"], [a, b]))
    assert p.status_code == 201, p.text
    draft = p.json()
    assert draft["status"] == "draft" and draft["total"] == "13010.00"  # 2 lines x 10 x 650.50
    assert qty(client, owner, store_id, a) == 0  # nothing moves while it is a draft

    got = client.post(f"/purchases/{draft['id']}/receive", headers=owner)
    assert (
        got.status_code == 200 and got.json()["status"] == "received" and got.json()["received_at"]
    )
    assert qty(client, owner, store_id, a) == qty(client, owner, store_id, b) == 10
    moves = client.get("/inventory/movements", headers=owner, params={"store_id": store_id}).json()
    assert {m["movement_type"] for m in moves} == {"purchase"}
    refreshed = client.get(f"/products/{product['id']}", headers=owner).json()
    assert {v["cost_price"] for v in refreshed["variants"]} == {"650.50"}  # latest purchase cost


def test_receiving_twice_is_refused_even_concurrently(
    client: TestClient,
    owner: dict[str, str],
    store_id: str,
    supplier: dict[str, Any],
    make_product: Any,
) -> None:
    v = make_product()["variants"][0]["id"]
    pid = client.post("/purchases", headers=owner, json=bill(store_id, supplier["id"], [v])).json()[
        "id"
    ]

    def receive(_: int) -> int:
        with TestClient(app) as c:
            return c.post(f"/purchases/{pid}/receive", headers=owner).status_code

    with ThreadPoolExecutor(max_workers=6) as pool:
        codes = sorted(pool.map(receive, range(6)))
    assert codes == [200, 409, 409, 409, 409, 409]
    assert qty(client, owner, store_id, v) == 10  # added once


def test_duplicate_bill_number_per_supplier(
    client: TestClient,
    owner: dict[str, str],
    store_id: str,
    supplier: dict[str, Any],
    make_product: Any,
) -> None:
    v = make_product()["variants"][0]["id"]
    assert (
        client.post(
            "/purchases", headers=owner, json=bill(store_id, supplier["id"], [v])
        ).status_code
        == 201
    )
    assert (
        client.post(
            "/purchases", headers=owner, json=bill(store_id, supplier["id"], [v])
        ).status_code
        == 409
    )
    other = client.post("/suppliers", headers=owner, json={"name": "Other Mills"}).json()
    assert (
        client.post("/purchases", headers=owner, json=bill(store_id, other["id"], [v])).status_code
        == 201
    )


def test_purchase_validation(
    client: TestClient,
    owner: dict[str, str],
    store_id: str,
    supplier: dict[str, Any],
    make_product: Any,
) -> None:
    v = make_product()["variants"][0]["id"]
    ok = bill(store_id, supplier["id"], [v])
    dup = {**ok, "items": ok["items"] * 2}
    assert client.post("/purchases", headers=owner, json=dup).status_code == 422
    assert client.post("/purchases", headers=owner, json={**ok, "items": []}).status_code == 422
    bad_qty = {**ok, "items": [{"variant_id": v, "quantity": 0, "unit_cost": "1.00"}]}
    assert client.post("/purchases", headers=owner, json=bad_qty).status_code == 422
    neg = {**ok, "items": [{"variant_id": v, "quantity": 1, "unit_cost": "-1.00"}]}
    assert client.post("/purchases", headers=owner, json=neg).status_code == 422
    unknown_variant = {
        **ok,
        "items": [{"variant_id": str(uuid.uuid4()), "quantity": 1, "unit_cost": "1.00"}],
    }
    assert client.post("/purchases", headers=owner, json=unknown_variant).status_code == 422
    assert (
        client.post(
            "/purchases", headers=owner, json={**ok, "supplier_id": str(uuid.uuid4())}
        ).status_code
        == 422
    )


def test_only_drafts_can_be_deleted(
    client: TestClient,
    owner: dict[str, str],
    store_id: str,
    supplier: dict[str, Any],
    make_product: Any,
) -> None:
    v = make_product()["variants"][0]["id"]
    d = client.post(
        "/purchases", headers=owner, json=bill(store_id, supplier["id"], [v], "D1")
    ).json()
    assert client.delete(f"/purchases/{d['id']}", headers=owner).status_code == 204
    assert client.get(f"/purchases/{d['id']}", headers=owner).status_code == 404
    r = client.post(
        "/purchases", headers=owner, json=bill(store_id, supplier["id"], [v], "D2")
    ).json()
    client.post(f"/purchases/{r['id']}/receive", headers=owner)
    assert client.delete(f"/purchases/{r['id']}", headers=owner).status_code == 409


def test_list_filters_by_status_and_store_scope(
    client: TestClient,
    owner: dict[str, str],
    store_id: str,
    supplier: dict[str, Any],
    make_product: Any,
    make_user: Any,
) -> None:
    v = make_product()["variants"][0]["id"]
    a = client.post(
        "/purchases", headers=owner, json=bill(store_id, supplier["id"], [v], "A")
    ).json()
    client.post("/purchases", headers=owner, json=bill(store_id, supplier["id"], [v], "B"))
    client.post(f"/purchases/{a['id']}/receive", headers=owner)
    params = {"store_id": store_id}
    assert len(client.get("/purchases", headers=owner, params=params).json()) == 2
    assert [
        p["bill_number"]
        for p in client.get(
            "/purchases", headers=owner, params={**params, "status": "received"}
        ).json()
    ] == ["A"]
    other = client.post(
        "/stores", headers=owner, json={"code": "B2", "name": "B2", "state_code": "27"}
    ).json()
    mgr = make_user("Manager", "mgr@example.com", store_ids=[other["id"]])
    assert client.get("/purchases", headers=mgr, params=params).status_code == 403
    assert client.get(f"/purchases/{a['id']}", headers=mgr).status_code == 403
    assert client.post(f"/purchases/{a['id']}/receive", headers=mgr).status_code == 403


def test_cashier_cannot_touch_purchasing(client: TestClient, make_user: Any, store_id: str) -> None:
    cashier = make_user("Cashier", "cash@example.com", store_ids=[store_id])
    assert client.get("/suppliers", headers=cashier).status_code == 403
    assert client.post("/suppliers", headers=cashier, json={"name": "S"}).status_code == 403
    assert (
        client.get("/purchases", headers=cashier, params={"store_id": store_id}).status_code == 403
    )
