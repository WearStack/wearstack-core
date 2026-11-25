import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.db.session import SessionLocal, engine
from app.models import Inventory, StockMovement
from app.services.inventory import InsufficientStock, apply_movement


def _move(
    client: TestClient,
    headers: dict[str, str],
    store: str,
    variant: str,
    kind: str,
    qty: int,
    reason: str | None = None,
) -> Any:
    return client.post(
        "/inventory/movements",
        headers=headers,
        json={
            "store_id": store,
            "variant_id": variant,
            "kind": kind,
            "quantity": qty,
            "reason": reason,
        },
    )


def _qty(client: TestClient, headers: dict[str, str], store: str, variant: str) -> int:
    rows = client.get("/inventory", headers=headers, params={"store_id": store}).json()
    return next(r["quantity"] for r in rows if r["variant_id"] == variant)


def test_unstocked_variants_show_zero(
    client: TestClient, owner: dict[str, str], store_id: str, make_product: Any
) -> None:
    make_product()
    rows = client.get("/inventory", headers=owner, params={"store_id": store_id}).json()
    assert len(rows) == 2 and all(r["quantity"] == 0 for r in rows)


def test_opening_then_adjustments_update_balance_and_ledger(
    client: TestClient, owner: dict[str, str], store_id: str, make_product: Any
) -> None:
    v = make_product()["variants"][0]["id"]
    assert _move(client, owner, store_id, v, "opening", 10).json()["balance_after"] == 10
    assert (
        _move(client, owner, store_id, v, "adjustment", -3, "damaged").json()["balance_after"] == 7
    )
    assert (
        _move(client, owner, store_id, v, "adjustment", 5, "found in storeroom").status_code == 201
    )
    assert _qty(client, owner, store_id, v) == 12

    history = client.get(
        "/inventory/movements", headers=owner, params={"store_id": store_id, "variant_id": v}
    ).json()
    assert [m["quantity_delta"] for m in history] == [5, -3, 10]  # newest first
    assert [m["balance_after"] for m in history] == [12, 7, 10]
    assert history[1]["reason"] == "damaged" and history[1]["user_id"]


def test_stock_cannot_go_negative(
    client: TestClient, owner: dict[str, str], store_id: str, make_product: Any
) -> None:
    v = make_product()["variants"][0]["id"]
    _move(client, owner, store_id, v, "opening", 2)
    res = _move(client, owner, store_id, v, "adjustment", -3, "oops")
    assert res.status_code == 409 and "Only 2" in res.json()["detail"]
    assert _qty(client, owner, store_id, v) == 2
    assert (
        len(client.get("/inventory/movements", headers=owner, params={"store_id": store_id}).json())
        == 1
    )


def test_adjustment_rules(
    client: TestClient, owner: dict[str, str], store_id: str, make_product: Any
) -> None:
    v = make_product()["variants"][0]["id"]
    assert _move(client, owner, store_id, v, "adjustment", 5).status_code == 422  # reason required
    assert _move(client, owner, store_id, v, "adjustment", 5, "  ").status_code == 422
    assert _move(client, owner, store_id, v, "adjustment", 0, "why").status_code == 422
    assert _move(client, owner, store_id, v, "opening", -4).status_code == 422
    assert _move(client, owner, store_id, v, "opening", 0).status_code == 422
    assert _move(client, owner, store_id, v, "opening", 4).status_code == 201
    assert _move(client, owner, store_id, v, "opening", 4).status_code == 409  # only once


def test_balance_always_equals_ledger_sum(
    client: TestClient, owner: dict[str, str], store_id: str, make_product: Any
) -> None:
    v = make_product()["variants"][0]["id"]
    _move(client, owner, store_id, v, "opening", 20)
    for delta in (-4, 7, -1, -9, 3):
        assert _move(client, owner, store_id, v, "adjustment", delta, "count").status_code == 201
    with SessionLocal() as db:
        ledger = db.scalar(
            select(func.sum(StockMovement.quantity_delta)).where(
                StockMovement.variant_id == uuid.UUID(v)
            )
        )
        balance = db.scalar(select(Inventory.quantity).where(Inventory.variant_id == uuid.UUID(v)))
    assert ledger == balance == 16


def test_concurrent_removals_never_oversell(
    client: TestClient, owner: dict[str, str], store_id: str, make_product: Any
) -> None:
    v = uuid.UUID(make_product()["variants"][0]["id"])
    me = client.get("/auth/me", headers=owner).json()
    biz, user, store = uuid.UUID(me["business_id"]), uuid.UUID(me["id"]), uuid.UUID(store_id)
    _move(client, owner, store_id, str(v), "opening", 5)

    def sell_one(_: int) -> bool:
        with SessionLocal() as db:
            try:
                apply_movement(
                    db,
                    business_id=biz,
                    store_id=store,
                    variant_id=v,
                    movement_type="sale",
                    delta=-1,
                    user_id=user,
                )
                db.commit()
                return True
            except InsufficientStock:
                db.rollback()
                return False

    with ThreadPoolExecutor(max_workers=10) as pool:
        results = list(pool.map(sell_one, range(20)))
    assert sum(results) == 5
    assert _qty(client, owner, store_id, str(v)) == 0
    with SessionLocal() as db:
        assert db.scalar(select(func.min(StockMovement.balance_after))) == 0


def test_database_rejects_negative_balance_even_if_service_is_bypassed(
    client: TestClient, owner: dict[str, str], store_id: str, make_product: Any
) -> None:
    from sqlalchemy.exc import IntegrityError

    v = make_product()["variants"][0]["id"]
    _move(client, owner, store_id, v, "opening", 1)
    with SessionLocal() as db, pytest.raises(IntegrityError):
        row = db.scalars(select(Inventory)).one()
        row.quantity = -1
        db.commit()


def test_reorder_level_and_low_stock_filter(
    client: TestClient, owner: dict[str, str], store_id: str, make_product: Any
) -> None:
    a, b = (v["id"] for v in make_product()["variants"])
    _move(client, owner, store_id, a, "opening", 3)
    _move(client, owner, store_id, b, "opening", 50)
    for v, level in ((a, 5), (b, 10)):
        res = client.put(
            "/inventory/reorder-level",
            headers=owner,
            json={"store_id": store_id, "variant_id": v, "reorder_level": level},
        )
        assert res.status_code == 204
    low = client.get(
        "/inventory", headers=owner, params={"store_id": store_id, "low_stock": True}
    ).json()
    assert [r["variant_id"] for r in low] == [a] and low[0]["low_stock"]
    assert _qty(client, owner, store_id, a) == 3  # setting the level did not touch stock


def test_inventory_search(
    client: TestClient, owner: dict[str, str], store_id: str, make_product: Any
) -> None:
    make_product("Linen Shirt")
    make_product("Denim Jeans")
    rows = client.get(
        "/inventory", headers=owner, params={"store_id": store_id, "q": "denim"}
    ).json()
    assert {r["product_name"] for r in rows} == {"Denim Jeans"}


def test_permissions_cashier_reads_but_cannot_adjust(
    client: TestClient, owner: dict[str, str], store_id: str, make_user: Any, make_product: Any
) -> None:
    v = make_product()["variants"][0]["id"]
    cashier = make_user("Cashier", "cash@example.com", store_ids=[store_id])
    assert (
        client.get("/inventory", headers=cashier, params={"store_id": store_id}).status_code == 200
    )
    assert _move(client, cashier, store_id, v, "opening", 5).status_code == 403
    res = client.put(
        "/inventory/reorder-level",
        headers=cashier,
        json={"store_id": store_id, "variant_id": v, "reorder_level": 1},
    )
    assert res.status_code == 403


def test_store_scoping(
    client: TestClient, owner: dict[str, str], store_id: str, make_user: Any, make_product: Any
) -> None:
    other = client.post(
        "/stores", headers=owner, json={"code": "B2", "name": "B2", "state_code": "27"}
    ).json()
    v = make_product()["variants"][0]["id"]
    mgr = make_user("Manager", "mgr@example.com", store_ids=[other["id"]])
    assert client.get("/inventory", headers=mgr, params={"store_id": store_id}).status_code == 403
    assert (
        client.get("/inventory/movements", headers=mgr, params={"store_id": store_id}).status_code
        == 403
    )
    assert _move(client, mgr, store_id, v, "opening", 5).status_code == 403
    assert _move(client, mgr, other["id"], v, "opening", 5).status_code == 201
    # Stock is per store: the owner's main store is unaffected.
    assert _qty(client, owner, store_id, v) == 0
    assert _qty(client, owner, other["id"], v) == 5
    lookup = client.get(
        "/variants/lookup", headers=owner, params={"q": "Shirt", "store_id": other["id"]}
    ).json()
    assert {r["variant_id"]: r["quantity"] for r in lookup}[v] == 5


def test_unknown_variant_is_404(client: TestClient, owner: dict[str, str], store_id: str) -> None:
    assert _move(client, owner, store_id, str(uuid.uuid4()), "opening", 1).status_code == 404


def test_stock_changes_are_audited(
    client: TestClient, owner: dict[str, str], store_id: str, make_product: Any
) -> None:
    v = make_product()["variants"][0]["id"]
    _move(client, owner, store_id, v, "opening", 4)
    _move(client, owner, store_id, v, "adjustment", -1, "sample given")
    logs = client.get("/audit-logs", headers=owner, params={"entity_type": "variant"}).json()
    assert [(e["action"], e["after"]["delta"]) for e in logs] == [
        ("stock.adjustment", -1),
        ("stock.opening", 4),
    ]
    assert logs[0]["after"]["reason"] == "sample given"


def test_movements_written_in_one_transaction_keep_their_order(
    client: TestClient, owner: dict[str, str], store_id: str, make_product: Any
) -> None:
    """A stock correction and the sale that needed it are one transaction and one timestamp; the
    history must still show them in the order they happened, every time."""
    v = uuid.UUID(make_product()["variants"][0]["id"])
    me = client.get("/auth/me", headers=owner).json()
    biz, user, store = uuid.UUID(me["business_id"]), uuid.UUID(me["id"]), uuid.UUID(store_id)
    for _ in range(25):  # a random tie-break would get this wrong about half of the time
        with SessionLocal() as db:
            for kind, delta in (("adjustment", 2), ("sale", -1), ("adjustment", 3), ("sale", -2)):
                apply_movement(
                    db,
                    business_id=biz,
                    store_id=store,
                    variant_id=v,
                    movement_type=kind,
                    delta=delta,
                    user_id=user,
                )
            db.commit()
        history = client.get(
            "/inventory/movements",
            headers=owner,
            params={"store_id": store_id, "variant_id": str(v), "limit": 4},
        ).json()
        assert [m["quantity_delta"] for m in reversed(history)] == [2, -1, 3, -2]
        assert [m["balance_after"] for m in reversed(history)][1:] == [
            history[-1]["balance_after"] - 1,
            history[-1]["balance_after"] + 2,
            history[-1]["balance_after"],
        ]
        with engine.begin() as conn:
            conn.exec_driver_sql("TRUNCATE stock_movements, inventory")
