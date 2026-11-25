import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from decimal import Decimal as D
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.db.session import SessionLocal, engine
from app.main import app
from app.models import Role
from tests.conftest import login

IST = ZoneInfo("Asia/Kolkata")
PRICE = "1299.00"


def ago(**kw: float) -> str:
    return (datetime.now(IST) - timedelta(**kw)).isoformat()


@pytest.fixture
def shop(
    client: TestClient, owner: dict[str, str], store_id: str, make_product: Any
) -> dict[str, Any]:
    """One product at 1299.00 (5% class, a test figure), 10 units of its first variant in stock."""
    rate = client.post(
        "/tax-rates",
        headers=owner,
        json={"name": "R5", "rate": "5", "effective_from": "2020-01-01"},
    ).json()["id"]
    product = make_product(price=PRICE, tax_rate_id=rate, hsn_code="6205")
    variant = product["variants"][0]["id"]
    client.post(
        "/inventory/movements",
        headers=owner,
        json={"store_id": store_id, "variant_id": variant, "kind": "opening", "quantity": 10},
    )
    return {"store": store_id, "variant": variant, "product": product, "rate": rate}


def register(
    client: TestClient,
    headers: dict[str, str],
    store: str,
    name: str = "Till 1",
    ident: str | None = None,
) -> str:
    res = client.post(
        "/devices",
        headers=headers,
        json={"identifier": ident or str(uuid.uuid4()), "name": name, "store_id": store},
    )
    assert res.status_code == 200, res.text
    return str(res.json()["id"])


def me(client: TestClient, headers: dict[str, str]) -> str:
    return str(client.get("/auth/me", headers=headers).json()["id"])


def sale_op(
    shop: dict[str, Any],
    cashier: str,
    qty: int = 1,
    price: str = PRICE,
    sold: str | None = None,
    discount: str = "0",
    pay: str | None = None,
    number: str = "OFF-A1B2-0001",
    variant: str | None = None,
) -> dict[str, Any]:
    total = D(price) * qty - D(discount)
    return {
        "client_operation_id": str(uuid.uuid4()),
        "store_id": shop["store"],
        "sold_at": sold or ago(hours=2),
        "cashier_id": cashier,
        "provisional_number": number,
        "items": [
            {
                "variant_id": variant or shop["variant"],
                "quantity": qty,
                "unit_price": price,
                "discount": discount,
            }
        ],
        "payments": [{"method": "cash", "amount": pay or f"{total.quantize(D('1')):.2f}"}],
    }


def post(client: TestClient, headers: dict[str, str], device: str, *ops: dict[str, Any]) -> Any:
    return client.post(
        "/sync/sales", headers=headers, json={"device_id": device, "operations": list(ops)}
    )


def stock(client: TestClient, owner: dict[str, str], shop: dict[str, Any]) -> int:
    rows = client.get("/inventory", headers=owner, params={"store_id": shop["store"]}).json()
    return int(next(r["quantity"] for r in rows if r["variant_id"] == shop["variant"]))


def sales_count(client: TestClient, owner: dict[str, str], shop: dict[str, Any]) -> int:
    return len(client.get("/sales", headers=owner, params={"store_id": shop["store"]}).json())


# ---- devices and catalogue ----
def test_device_registration_is_idempotent_and_store_scoped(
    client: TestClient, owner: dict[str, str], store_id: str, make_user: Any
) -> None:
    ident = str(uuid.uuid4())
    a = register(client, owner, store_id, "Front till", ident)
    b = register(client, owner, store_id, "Front till (renamed)", ident)
    assert a == b  # same browser, same device
    listed = client.get("/devices", headers=owner).json()
    assert [d["name"] for d in listed] == ["Front till (renamed)"]
    other = client.post(
        "/stores", headers=owner, json={"code": "B2", "name": "B2", "state_code": "27"}
    ).json()
    cashier = make_user("Cashier", "cash@example.com", store_ids=[store_id])
    res = client.post(
        "/devices",
        headers=cashier,
        json={"identifier": str(uuid.uuid4()), "name": "x", "store_id": other["id"]},
    )
    assert res.status_code == 403  # not their store
    assert client.get("/devices", headers=cashier).status_code == 403  # listing needs sync:resolve
    assert (
        client.post(
            "/devices", json={"identifier": "x" * 10, "name": "n", "store_id": store_id}
        ).status_code
        == 401
    )


def test_catalogue_snapshot_has_what_an_offline_till_needs(
    client: TestClient, owner: dict[str, str], shop: dict[str, Any], make_product: Any
) -> None:
    unrated = make_product("No Rate Tee", price="500.00")["variants"][0]["id"]  # cannot be billed
    inactive = make_product("Retired Tee", price="500.00", tax_rate_id=shop["rate"])
    client.patch(f"/products/{inactive['id']}", headers=owner, json={"is_active": False})
    client.post(
        "/customers",
        headers=owner,
        json={"name": "Asha Rao", "phone": "9876543210", "state_code": "29"},
    )
    snap = client.get("/sync/catalog", headers=owner, params={"store_id": shop["store"]}).json()
    by_id = {v["id"]: v for v in snap["variants"]}
    v = by_id[shop["variant"]]
    assert (v["price"], v["quantity"], v["sellable"], v["hsn_code"]) == (PRICE, 10, True, "6205")
    assert len(v["barcode"]) == 13 and v["sku"]
    assert by_id[unrated]["sellable"] is False  # no GST rate: the till must not offer it
    assert by_id[inactive["variants"][0]["id"]]["sellable"] is False
    assert [c["name"] for c in snap["customers"]] == ["Asha Rao"]
    assert snap["settings"] == {
        "free_discount_percent": 10,
        "offline_warn_hours": 24,
        "offline_block_hours": 72,
        "offline_max_sale_age_days": 7,
        "sync_batch_max": 50,
    }
    assert snap["store_name"] == "Main Store" and snap["generated_at"]


def test_catalogue_scoping_and_permissions(
    client: TestClient, owner: dict[str, str], store_id: str, make_user: Any
) -> None:
    other = client.post(
        "/stores", headers=owner, json={"code": "B2", "name": "B2", "state_code": "27"}
    ).json()
    cashier = make_user("Cashier", "cash@example.com", store_ids=[store_id])
    assert (
        client.get("/sync/catalog", headers=cashier, params={"store_id": other["id"]}).status_code
        == 403
    )
    assert (
        client.get("/sync/catalog", headers=cashier, params={"store_id": store_id}).status_code
        == 200
    )
    assert client.get("/sync/catalog", params={"store_id": store_id}).status_code == 401
    assert (
        client.get(
            "/sync/catalog",
            headers=owner,
            params={"store_id": store_id, "device_id": str(uuid.uuid4())},
        ).status_code
        == 404
    )


def test_pick_rate_matches_the_sql_resolver(client: TestClient, owner: dict[str, str]) -> None:
    from datetime import date

    from app.models import Business
    from app.services.tax import load_rates, pick_rate, resolve_tax_rate

    for body in (
        {"name": "S", "rate": "5", "max_unit_price": "1000", "effective_to": "2025-12-31"},
        {"name": "S", "rate": "12", "min_unit_price": "1000", "effective_to": "2025-12-31"},
        {"name": "S", "rate": "7", "max_unit_price": "1000", "effective_from": "2026-01-01"},
    ):
        r = client.post("/tax-rates", headers=owner, json={"effective_from": "2020-01-01", **body})
        assert r.status_code == 201, r.text
    with SessionLocal() as db:
        biz = db.query(Business).one()
        rates = load_rates(db, biz.id)
        base = next(iter(rates))
        for on in (date(2024, 1, 1), date(2026, 6, 1), date(2019, 1, 1)):
            for price in (D("0.01"), D("999.99"), D("1000"), D("1000.01"), D("5000")):
                a = resolve_tax_rate(db, base, on, price)
                b = pick_rate(rates, base, on, price)
                assert (a.id if a else None) == (b.id if b else None), (on, price)


# ---- applying offline sales ----
def test_an_offline_sale_becomes_a_real_sale_dated_when_it_happened(
    client: TestClient, owner: dict[str, str], shop: dict[str, Any]
) -> None:
    device = register(client, owner, shop["store"])
    op = sale_op(shop, me(client, owner), qty=2, sold=ago(hours=5), pay="2598.00")
    res = post(client, owner, device, op)
    assert res.status_code == 200, res.text
    r = res.json()["results"][0]
    assert r["status"] == "applied" and r["sale_id"] and r["invoice_number"]
    assert r["client_operation_id"] == op["client_operation_id"]
    sale = client.get(f"/sales/{r['sale_id']}", headers=owner).json()
    assert sale["grand_total"] == "2598.00" and sale["invoice_number"] == r["invoice_number"]
    assert (
        sale["items"][0]["unit_price"] == "1299.00" and sale["payments"][0]["status"] == "confirmed"
    )
    assert stock(client, owner, shop) == 8
    # The sale carries the time it really happened; the invoice is issued (and numbered) now.
    with engine.connect() as conn:
        sold, issued = conn.execute(
            text(
                "SELECT s.sold_at, d.issued_at FROM sales s "
                "JOIN gst_documents d ON d.sale_id = s.id"
            )
        ).one()
    assert (issued - sold) > timedelta(hours=4, minutes=50)
    assert abs(issued - datetime.now(IST)) < timedelta(minutes=2)


def test_resending_the_same_sale_changes_nothing(
    client: TestClient, owner: dict[str, str], shop: dict[str, Any]
) -> None:
    device = register(client, owner, shop["store"])
    op = sale_op(shop, me(client, owner))
    first = post(client, owner, device, op).json()["results"][0]
    again = post(client, owner, device, op).json()["results"][0]
    third = post(client, owner, device, op, op).json()["results"]  # even twice in one batch
    assert first["status"] == again["status"] == "applied"
    assert first["sale_id"] == again["sale_id"] == third[0]["sale_id"] == third[1]["sale_id"]
    assert first["invoice_number"] == again["invoice_number"]
    assert stock(client, owner, shop) == 9 and sales_count(client, owner, shop) == 1


def test_one_bad_sale_does_not_block_the_others(
    client: TestClient, owner: dict[str, str], shop: dict[str, Any]
) -> None:
    device = register(client, owner, shop["store"])
    cashier = me(client, owner)
    good1, good2 = sale_op(shop, cashier, number="OFF-1"), sale_op(shop, cashier, number="OFF-3")
    bad = sale_op(shop, cashier, number="OFF-2", variant=str(uuid.uuid4()))
    results = post(client, owner, device, good1, bad, good2).json()["results"]
    assert [r["status"] for r in results] == ["applied", "failed", "applied"]
    assert results[1]["error_code"] == "unknown_variant"
    assert stock(client, owner, shop) == 8


def test_invoice_numbers_follow_sync_order_and_stay_gap_free(
    client: TestClient, owner: dict[str, str], shop: dict[str, Any]
) -> None:
    device = register(client, owner, shop["store"])
    cashier = me(client, owner)
    later_sale = sale_op(shop, cashier, sold=ago(hours=1), number="OFF-2")
    earlier_sale = sale_op(shop, cashier, sold=ago(hours=6), number="OFF-1")
    r = post(client, owner, device, later_sale, earlier_sale).json()["results"]
    numbers = [x["invoice_number"] for x in r]
    assert [n.split("/")[-1] for n in numbers] == ["00001", "00002"]  # issued in the order synced


def test_reports_date_an_offline_sale_by_when_it_happened(
    client: TestClient, owner: dict[str, str], shop: dict[str, Any]
) -> None:
    device = register(client, owner, shop["store"])
    three_days_ago = datetime.now(IST) - timedelta(days=3)
    post(client, owner, device, sale_op(shop, me(client, owner), sold=three_days_ago.isoformat()))
    day = three_days_ago.date().isoformat()
    on_day = client.get("/reports/sales", headers=owner, params={"from": day, "to": day}).json()
    assert on_day["totals"]["orders"] == 1
    today = datetime.now(IST).date().isoformat()
    assert (
        client.get("/reports/sales", headers=owner, params={"from": today, "to": today}).json()[
            "totals"
        ]["orders"]
        == 0
    )


def test_a_sale_already_recorded_online_is_linked_not_duplicated(
    client: TestClient, owner: dict[str, str], shop: dict[str, Any]
) -> None:
    """The connection dropped after the server saved the sale but before the reply arrived."""
    device = register(client, owner, shop["store"])
    op = sale_op(shop, me(client, owner), pay="1299.00")
    online = client.post(
        "/sales",
        headers=owner,
        json={
            "idempotency_key": op["client_operation_id"],
            "store_id": shop["store"],
            "items": [{"variant_id": shop["variant"], "quantity": 1}],
            "payments": [{"method": "cash", "amount": "1299.00"}],
        },
    ).json()
    r = post(client, owner, device, op).json()["results"][0]
    assert r["status"] == "applied" and r["sale_id"] == online["id"]
    assert r["invoice_number"] == online["invoice_number"]
    assert stock(client, owner, shop) == 9 and sales_count(client, owner, shop) == 1


# ---- who made the sale ----
def test_the_sale_is_attributed_to_the_cashier_even_if_someone_else_syncs(
    client: TestClient, owner: dict[str, str], shop: dict[str, Any], make_user: Any
) -> None:
    cashier = make_user("Cashier", "cash@example.com", store_ids=[shop["store"]])
    cashier_id = me(client, cashier)
    device = register(client, owner, shop["store"])
    r = post(client, owner, device, sale_op(shop, cashier_id)).json()["results"][
        0
    ]  # the owner syncs
    with engine.connect() as conn:
        user_id = conn.execute(
            text("SELECT user_id FROM sales WHERE id = :i"), {"i": r["sale_id"]}
        ).scalar()
    assert str(user_id) == cashier_id


def test_sales_by_unknown_or_unauthorised_cashiers_fail(
    client: TestClient, owner: dict[str, str], shop: dict[str, Any], make_user: Any
) -> None:
    device = register(client, owner, shop["store"])
    other = client.post(
        "/stores", headers=owner, json={"code": "B2", "name": "B2", "state_code": "27"}
    ).json()
    elsewhere = make_user("Cashier", "far@example.com", store_ids=[other["id"]])
    gone = make_user("Cashier", "gone@example.com", store_ids=[shop["store"]])
    gone_id = me(client, gone)
    client.patch(f"/users/{gone_id}", headers=owner, json={"is_active": False})
    for cashier, code in (
        (str(uuid.uuid4()), "cashier_invalid"),
        (gone_id, "cashier_invalid"),
        (me(client, elsewhere), "cashier_no_store"),
    ):
        r = post(client, owner, device, sale_op(shop, cashier)).json()["results"][0]
        assert (r["status"], r["error_code"]) == ("failed", code)
    assert stock(client, owner, shop) == 10


def test_a_cashier_cannot_get_a_big_discount_through_offline_sync(
    client: TestClient, owner: dict[str, str], shop: dict[str, Any], make_user: Any
) -> None:
    cashier = make_user("Cashier", "cash@example.com", store_ids=[shop["store"]])
    device = register(client, cashier, shop["store"])
    big = sale_op(shop, me(client, cashier), discount="500.00")  # > 10% and no sale:discount
    r = post(client, cashier, device, big).json()["results"][0]
    assert (r["status"], r["error_code"]) == ("failed", "discount_not_allowed")
    ok = sale_op(shop, me(client, cashier), discount="100.00")
    assert post(client, cashier, device, ok).json()["results"][0]["status"] == "applied"


# ---- validation ----
def test_dates_are_checked(client: TestClient, owner: dict[str, str], shop: dict[str, Any]) -> None:
    device = register(client, owner, shop["store"])
    cashier = me(client, owner)
    future = post(
        client,
        owner,
        device,
        sale_op(shop, cashier, sold=(datetime.now(IST) + timedelta(hours=2)).isoformat()),
    )
    assert future.json()["results"][0]["error_code"] == "sold_at_in_future"
    soon = (datetime.now(IST) + timedelta(minutes=2)).isoformat()  # clock drift is tolerated
    assert (
        post(client, owner, device, sale_op(shop, cashier, sold=soon)).json()["results"][0][
            "status"
        ]
        == "applied"
    )
    naive = sale_op(shop, cashier)
    naive["sold_at"] = "2026-11-20T10:00:00"  # no timezone: refused outright
    assert post(client, owner, device, naive).status_code == 422


def test_payment_and_payload_validation(
    client: TestClient, owner: dict[str, str], shop: dict[str, Any]
) -> None:
    device = register(client, owner, shop["store"])
    cashier = me(client, owner)
    short = sale_op(shop, cashier, pay="1000.00")
    r = post(client, owner, device, short).json()["results"][0]
    assert r["status"] == "failed" and "must match" in r["error_message"]
    upi = sale_op(shop, cashier)
    upi["payments"] = [{"method": "upi", "amount": "1299.00"}]  # no reference
    assert post(client, owner, device, upi).status_code == 422
    assert post(client, owner, device).status_code == 422  # nothing to send
    empty = sale_op(shop, cashier)
    empty["items"] = []
    assert post(client, owner, device, empty).status_code == 422
    assert stock(client, owner, shop) == 10


def test_batch_limits_and_device_checks(
    client: TestClient, owner: dict[str, str], shop: dict[str, Any]
) -> None:
    device = register(client, owner, shop["store"])
    cashier = me(client, owner)
    too_many = [sale_op(shop, cashier) for _ in range(51)]
    assert post(client, owner, device, *too_many).status_code == 422
    assert post(client, owner, str(uuid.uuid4()), sale_op(shop, cashier)).status_code == 404
    other = client.post(
        "/stores", headers=owner, json={"code": "B2", "name": "B2", "state_code": "27"}
    ).json()
    wrong_store = sale_op(shop, cashier)
    wrong_store["store_id"] = other["id"]
    assert post(client, owner, device, wrong_store).status_code == 422
    assert (
        client.post("/sync/sales", json={"device_id": device, "operations": []}).status_code == 401
    )


# ---- conflicts ----
def test_not_enough_stock_is_held_for_a_manager_not_dropped(
    client: TestClient, owner: dict[str, str], shop: dict[str, Any]
) -> None:
    device = register(client, owner, shop["store"])
    op = sale_op(shop, me(client, owner), qty=12, pay="15588.00")  # only 10 in stock
    r = post(client, owner, device, op).json()["results"][0]
    assert r["status"] == "conflict" and r["sale_id"] is None and r["invoice_number"] is None
    c = r["conflicts"][0]
    assert (c["code"], c["requested"], c["available"]) == ("insufficient_stock", 12, 10)
    assert c["product_name"] == "Classic Shirt"
    assert (
        stock(client, owner, shop) == 10 and sales_count(client, owner, shop) == 0
    )  # nothing booked
    # It is on record, and asking again gives the same answer without re-deciding.
    again = post(client, owner, device, op).json()["results"][0]
    assert again["status"] == "conflict" and again["operation_id"] == r["operation_id"]
    ops = client.get("/sync/operations", headers=owner, params={"store_id": shop["store"]}).json()
    assert [(o["status"], o["total"]) for o in ops] == [("conflict", "15588.00")]
    # No invoice number was burned by the held sale.
    ok = post(client, owner, device, sale_op(shop, me(client, owner))).json()["results"][0]
    assert ok["invoice_number"].endswith("/00001")


def test_accepting_a_stock_conflict_books_the_sale_with_a_visible_correction(
    client: TestClient, owner: dict[str, str], shop: dict[str, Any]
) -> None:
    device = register(client, owner, shop["store"])
    r = post(
        client, owner, device, sale_op(shop, me(client, owner), qty=12, pay="15588.00")
    ).json()["results"][0]
    res = client.post(
        f"/sync/operations/{r['operation_id']}/resolve",
        headers=owner,
        json={"action": "accept", "note": "Counted the shelf: we really sold 12"},
    )
    assert res.status_code == 200, res.text
    op = res.json()
    assert op["status"] == "applied" and op["sale_id"] and op["invoice_number"]
    assert op["resolution_note"] == "Counted the shelf: we really sold 12"
    assert stock(client, owner, shop) == 0  # never negative
    moves = client.get(
        "/inventory/movements",
        headers=owner,
        params={"store_id": shop["store"], "variant_id": shop["variant"]},
    ).json()
    kinds = [(m["movement_type"], m["quantity_delta"]) for m in reversed(moves)]
    assert kinds == [
        ("opening", 10),
        ("adjustment", 2),
        ("sale", -12),
    ]  # the correction is in the ledger
    assert "Offline sale OFF-A1B2-0001" in next(
        m["reason"] for m in moves if m["movement_type"] == "adjustment"
    )
    logs = client.get("/audit-logs", headers=owner, params={"entity_type": "sync_operation"}).json()
    assert {"sync.conflict", "sync.accept"} <= {e["action"] for e in logs}
    sale_log = client.get("/audit-logs", headers=owner, params={"entity_type": "sale"}).json()[0]
    assert sale_log["after"]["stock_corrections"][0]["added"] == 2


def test_rejecting_needs_a_reason_and_books_nothing(
    client: TestClient, owner: dict[str, str], shop: dict[str, Any]
) -> None:
    device = register(client, owner, shop["store"])
    op = sale_op(shop, me(client, owner), qty=12, pay="15588.00")
    r = post(client, owner, device, op).json()["results"][0]
    url = f"/sync/operations/{r['operation_id']}/resolve"
    assert (
        client.post(url, headers=owner, json={"action": "reject"}).status_code == 409
    )  # a note is required
    rejected = client.post(
        url, headers=owner, json={"action": "reject", "note": "Customer returned the goods"}
    )
    assert rejected.status_code == 200 and rejected.json()["status"] == "rejected"
    assert stock(client, owner, shop) == 10 and sales_count(client, owner, shop) == 0
    assert (
        post(client, owner, device, op).json()["results"][0]["status"] == "rejected"
    )  # stays decided
    assert (
        client.post(url, headers=owner, json={"action": "accept"}).status_code == 409
    )  # no longer pending


def test_retry_succeeds_once_the_stock_has_been_received(
    client: TestClient, owner: dict[str, str], shop: dict[str, Any]
) -> None:
    device = register(client, owner, shop["store"])
    r = post(
        client, owner, device, sale_op(shop, me(client, owner), qty=12, pay="15588.00")
    ).json()["results"][0]
    url = f"/sync/operations/{r['operation_id']}/resolve"
    still = client.post(url, headers=owner, json={"action": "retry"}).json()
    assert still["status"] == "conflict"  # nothing changed, still short
    client.post(
        "/inventory/movements",
        headers=owner,
        json={
            "store_id": shop["store"],
            "variant_id": shop["variant"],
            "kind": "adjustment",
            "quantity": 5,
            "reason": "Found more in the storeroom",
        },
    )
    done = client.post(url, headers=owner, json={"action": "retry"}).json()
    assert done["status"] == "applied" and stock(client, owner, shop) == 3
    moves = client.get(
        "/inventory/movements",
        headers=owner,
        params={"store_id": shop["store"], "variant_id": shop["variant"]},
    ).json()
    assert "adjustment" not in [
        m["movement_type"] for m in moves if m["reason"] and "Offline" in m["reason"]
    ]


def test_a_changed_price_is_a_conflict_and_accepting_keeps_the_price_the_customer_paid(
    client: TestClient, owner: dict[str, str], shop: dict[str, Any]
) -> None:
    device = register(client, owner, shop["store"])
    client.patch(
        f"/products/{shop['product']['id']}", headers=owner, json={"selling_price": "1399.00"}
    )
    op = sale_op(shop, me(client, owner), price=PRICE)  # charged at the old price
    r = post(client, owner, device, op).json()["results"][0]
    assert r["status"] == "conflict"
    c = r["conflicts"][0]
    assert (c["code"], c["charged"], c["current"]) == ("price_changed", "1299.00", "1399.00")
    assert stock(client, owner, shop) == 10
    done = client.post(
        f"/sync/operations/{r['operation_id']}/resolve", headers=owner, json={"action": "accept"}
    ).json()
    sale = client.get(f"/sales/{done['sale_id']}", headers=owner).json()
    assert (
        sale["items"][0]["unit_price"] == "1299.00" and sale["grand_total"] == "1299.00"
    )  # as charged


def test_a_product_deactivated_since_the_sale_is_a_conflict(
    client: TestClient, owner: dict[str, str], shop: dict[str, Any]
) -> None:
    device = register(client, owner, shop["store"])
    client.patch(f"/products/{shop['product']['id']}", headers=owner, json={"is_active": False})
    r = post(client, owner, device, sale_op(shop, me(client, owner))).json()["results"][0]
    assert r["status"] == "conflict" and r["conflicts"][0]["code"] == "product_inactive"
    done = client.post(
        f"/sync/operations/{r['operation_id']}/resolve", headers=owner, json={"action": "accept"}
    ).json()
    assert done["status"] == "applied"


def test_a_very_old_offline_sale_needs_a_manager(
    client: TestClient, owner: dict[str, str], shop: dict[str, Any]
) -> None:
    device = register(client, owner, shop["store"])
    r = post(client, owner, device, sale_op(shop, me(client, owner), sold=ago(days=10))).json()[
        "results"
    ][0]
    assert r["status"] == "conflict" and r["conflicts"][0] == {
        "code": "sale_too_old",
        "sold_at": r["conflicts"][0]["sold_at"],
        "max_days": 7,
    }
    done = client.post(
        f"/sync/operations/{r['operation_id']}/resolve", headers=owner, json={"action": "accept"}
    ).json()
    assert done["status"] == "applied"


def test_a_failure_without_a_gst_rate_can_be_fixed_and_retried(
    client: TestClient, owner: dict[str, str], store_id: str, make_product: Any
) -> None:
    unrated = make_product("Unrated Tee", price="500.00")["variants"][0]["id"]
    client.post(
        "/inventory/movements",
        headers=owner,
        json={"store_id": store_id, "variant_id": unrated, "kind": "opening", "quantity": 5},
    )
    shop = {"store": store_id, "variant": unrated}
    device = register(client, owner, store_id)
    r = post(client, owner, device, sale_op(shop, me(client, owner), price="500.00")).json()[
        "results"
    ][0]
    assert (r["status"], r["error_code"]) == ("failed", "no_tax_rate")
    url = f"/sync/operations/{r['operation_id']}/resolve"
    assert (
        client.post(url, headers=owner, json={"action": "accept"}).status_code == 409
    )  # a failure cannot be accepted
    rate = client.post(
        "/tax-rates",
        headers=owner,
        json={"name": "R5", "rate": "5", "effective_from": "2020-01-01"},
    ).json()["id"]
    pid = client.get("/products", headers=owner).json()[0]["id"]
    client.patch(f"/products/{pid}", headers=owner, json={"tax_rate_id": rate})
    assert client.post(url, headers=owner, json={"action": "retry"}).json()["status"] == "applied"


def test_two_devices_selling_the_last_unit_never_oversell(
    client: TestClient, owner: dict[str, str], shop: dict[str, Any]
) -> None:
    """Both tills sold the last shirt while offline. Whoever syncs second gets a conflict."""
    client.post(
        "/inventory/movements",
        headers=owner,
        json={
            "store_id": shop["store"],
            "variant_id": shop["variant"],
            "kind": "adjustment",
            "quantity": -9,
            "reason": "Stock take",
        },
    )  # exactly one left
    assert stock(client, owner, shop) == 1
    cashier = me(client, owner)
    devices = [register(client, owner, shop["store"], f"Till {i}") for i in (1, 2)]
    ops = [sale_op(shop, cashier, number=f"OFF-{i}") for i in (1, 2)]

    def go(i: int) -> str:
        with TestClient(app) as c:
            return str(post(c, owner, devices[i], ops[i]).json()["results"][0]["status"])

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = sorted(pool.map(go, (0, 1)))
    assert statuses == ["applied", "conflict"]
    assert stock(client, owner, shop) == 0 and sales_count(client, owner, shop) == 1
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM inventory WHERE quantity < 0")).scalar() == 0
        assert (
            conn.execute(
                text("SELECT count(*) FROM sync_operations WHERE status='conflict'")
            ).scalar()
            == 1
        )


# ---- visibility and permissions ----
def test_cashiers_see_only_their_own_sales_and_cannot_resolve(
    client: TestClient, owner: dict[str, str], shop: dict[str, Any], make_user: Any
) -> None:
    c1 = make_user("Cashier", "one@example.com", store_ids=[shop["store"]])
    c2 = make_user("Cashier", "two@example.com", store_ids=[shop["store"]])
    d1, d2 = register(client, c1, shop["store"], "One"), register(client, c2, shop["store"], "Two")
    r1 = post(client, c1, d1, sale_op(shop, me(client, c1), qty=12, pay="15588.00")).json()[
        "results"
    ][0]
    post(client, c2, d2, sale_op(shop, me(client, c2)))
    params = {"store_id": shop["store"]}
    assert [
        o["cashier_name"] for o in client.get("/sync/operations", headers=c1, params=params).json()
    ] == ["one"]
    assert len(client.get("/sync/operations", headers=c2, params=params).json()) == 1
    assert (
        len(client.get("/sync/operations", headers=owner, params=params).json()) == 2
    )  # a manager sees all
    url = f"/sync/operations/{r1['operation_id']}"
    assert client.get(url, headers=c1).status_code == 200
    assert client.get(url, headers=c2).status_code == 404  # someone else's
    assert client.post(url + "/resolve", headers=c1, json={"action": "accept"}).status_code == 403
    detail = client.get(url, headers=owner).json()
    assert detail["lines"][0]["product_name"] == "Classic Shirt" and detail["device_name"] == "One"


def test_conflicts_in_other_businesses_are_invisible(
    client: TestClient, owner: dict[str, str], shop: dict[str, Any]
) -> None:
    from app.models import Business, Device, Store, User

    device = register(client, owner, shop["store"])
    r = post(
        client, owner, device, sale_op(shop, me(client, owner), qty=12, pay="15588.00")
    ).json()["results"][0]
    with SessionLocal() as db:
        biz = Business(name="Other", state_code="29")
        db.add(biz)
        db.flush()
        db.add(Store(business_id=biz.id, code="OT", name="Other", state_code="29"))
        db.commit()
        assert db.query(Device).count() == 1 and db.query(User).count() >= 1
    # The first business's owner still sees exactly its own operation.
    assert (
        len(
            client.get("/sync/operations", headers=owner, params={"store_id": shop["store"]}).json()
        )
        == 1
    )
    assert client.get(f"/sync/operations/{r['operation_id']}", headers=owner).status_code == 200


def test_new_permission_is_given_to_owner_and_manager_only(
    client: TestClient, owner: dict[str, str]
) -> None:
    roles = {r["name"]: r["permissions"] for r in client.get("/roles", headers=owner).json()}
    assert "sync:resolve" in roles["Owner"] and "sync:resolve" in roles["Manager"]
    assert "sync:resolve" not in roles["Cashier"]
    with SessionLocal() as db:
        assert db.query(Role).filter(Role.is_system).count() == 3
    assert login  # shared helper import kept for parity with the other test modules


def test_shared_offline_vectors_match_the_server_arithmetic() -> None:
    """The browser's offline rules are checked against this same file, so they cannot drift."""
    import importlib.util
    import json
    from pathlib import Path

    shared = Path(__file__).resolve().parents[2] / "shared"
    spec = importlib.util.spec_from_file_location(
        "make_vectors", shared / "make_offline_vectors.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    expected = mod.build()
    for target in mod.TARGETS:  # the reference copy and the copy next to the browser tests
        assert json.loads(Path(target).read_text()) == expected, target
