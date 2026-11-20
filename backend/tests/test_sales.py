import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from decimal import Decimal as D
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.config import get_settings
from app.db.session import SessionLocal, engine
from app.main import app
from app.services.gst import financial_year
from tests.conftest import login

FY = financial_year(datetime.now(ZoneInfo("Asia/Kolkata")).date())
PREFIX = f"MAIN/{FY[2:4]}-{FY[5:7]}/"


def _rate(client: TestClient, owner: dict[str, str], rate: str = "5", **kw: Any) -> str:
    body = {
        "name": f"R{rate}{kw.get('max_unit_price', '')}",
        "rate": rate,
        "effective_from": "2020-01-01",
        **kw,
    }
    res = client.post("/tax-rates", headers=owner, json=body)
    assert res.status_code == 201, res.text
    return str(res.json()["id"])


@pytest.fixture
def shop(
    client: TestClient, owner: dict[str, str], store_id: str, make_product: Any
) -> dict[str, Any]:
    """A product at 1299.00 under a 5% class (test figure), 10 units of each variant in stock."""
    rate_id = _rate(client, owner, "5")
    product = make_product(price="1299.00", tax_rate_id=rate_id, hsn_code="6205")
    for v in product["variants"]:
        client.post(
            "/inventory/movements",
            headers=owner,
            json={"store_id": store_id, "variant_id": v["id"], "kind": "opening", "quantity": 10},
        )
    return {
        "product": product,
        "variant": product["variants"][0]["id"],
        "store": store_id,
        "rate_id": rate_id,
    }


def sale_body(
    shop: dict[str, Any], qty: int = 1, pay: str | None = "1299.00", **extra: Any
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "idempotency_key": str(uuid.uuid4()),
        "store_id": shop["store"],
        "items": [{"variant_id": shop["variant"], "quantity": qty}],
        "payments": [{"method": "cash", "amount": pay}] if pay else [],
        **extra,
    }
    return body


def stock(
    client: TestClient, owner: dict[str, str], shop: dict[str, Any], variant: str | None = None
) -> int:
    rows = client.get("/inventory", headers=owner, params={"store_id": shop["store"]}).json()
    return int(next(r["quantity"] for r in rows if r["variant_id"] == (variant or shop["variant"])))


def test_sale_computes_tax_and_issues_invoice(
    client: TestClient, owner: dict[str, str], shop: dict[str, Any]
) -> None:
    res = client.post("/sales", headers=owner, json=sale_body(shop, qty=2, pay="2598.00"))
    assert res.status_code == 201, res.text
    s = res.json()
    assert s["invoice_number"] == PREFIX + "00001"
    assert len(s["invoice_number"]) <= 16
    # 2 x 1299.00 = 2598.00 inclusive of 5%: taxable 2474.29, tax 123.71 split 61.86 / 61.85.
    assert (s["taxable_total"], s["cgst_total"], s["sgst_total"], s["igst_total"]) == (
        "2474.29",
        "61.86",
        "61.85",
        "0.00",
    )
    assert (s["grand_total"], s["round_off"]) == ("2598.00", "0.00")
    line = s["items"][0]
    assert (line["quantity"], line["unit_price"], line["tax_rate"], line["hsn_code"]) == (
        2,
        "1299.00",
        "5.00",
        "6205",
    )
    assert s["payments"][0]["status"] == "confirmed"
    assert s["is_interstate"] is False and s["replayed"] is False
    assert stock(client, owner, shop) == 8


def test_totals_are_consistent(
    client: TestClient, owner: dict[str, str], shop: dict[str, Any]
) -> None:
    body = sale_body(shop, qty=3, pay="3897.00")
    body["items"].append(
        {"variant_id": shop["product"]["variants"][1]["id"], "quantity": 2, "discount": "100.00"}
    )
    body["payments"] = [{"method": "cash", "amount": "3897.00"}]
    total = D("3897.00") + D("2598.00") - D("100.00")
    body["payments"][0]["amount"] = str(total)
    s = client.post("/sales", headers=owner, json=body).json()
    lines_total = sum(D(i["line_total"]) for i in s["items"])
    assert lines_total + D(s["round_off"]) == D(s["grand_total"]) == total
    assert (
        D(s["taxable_total"]) + D(s["cgst_total"]) + D(s["sgst_total"]) + D(s["igst_total"])
        == lines_total
    )
    assert D(s["discount_total"]) == D("100.00")
    assert sum(D(i["taxable_value"]) for i in s["items"]) == D(s["taxable_total"])


def test_total_is_rounded_to_the_rupee_with_explicit_round_off(
    client: TestClient, owner: dict[str, str], store_id: str, make_product: Any
) -> None:
    p = make_product(price="999.99", tax_rate_id=_rate(client, owner))
    v = p["variants"][0]["id"]
    client.post(
        "/inventory/movements",
        headers=owner,
        json={"store_id": store_id, "variant_id": v, "kind": "opening", "quantity": 5},
    )
    body = {
        "idempotency_key": str(uuid.uuid4()),
        "store_id": store_id,
        "items": [{"variant_id": v, "quantity": 1}],
    }
    short = client.post(
        "/sales", headers=owner, json={**body, "payments": [{"method": "cash", "amount": "999.99"}]}
    )
    assert short.status_code == 422 and "1000.00" in short.json()["detail"]
    ok = client.post(
        "/sales",
        headers=owner,
        json={**body, "payments": [{"method": "cash", "amount": "1000.00"}]},
    )
    assert ok.status_code == 201
    assert (ok.json()["round_off"], ok.json()["grand_total"]) == ("0.01", "1000.00")


def test_payments_must_match_total_and_failure_changes_nothing(
    client: TestClient, owner: dict[str, str], shop: dict[str, Any]
) -> None:
    for pay in ("1000.00", "1300.00", None):
        res = client.post("/sales", headers=owner, json=sale_body(shop, pay=pay))
        assert res.status_code == 422, (pay, res.text)
    assert stock(client, owner, shop) == 10  # no stock left the shelf
    assert client.get("/sales", headers=owner, params={"store_id": shop["store"]}).json() == []
    # ...and no invoice number was burned by the failed attempts.
    ok = client.post("/sales", headers=owner, json=sale_body(shop))
    assert ok.json()["invoice_number"] == PREFIX + "00001"


def test_split_payments_with_reference(
    client: TestClient, owner: dict[str, str], shop: dict[str, Any]
) -> None:
    body = sale_body(shop, pay=None)
    body["payments"] = [
        {"method": "cash", "amount": "500.00"},
        {"method": "upi", "amount": "799.00", "reference": "UPI123456"},
    ]
    s = client.post("/sales", headers=owner, json=body).json()
    assert [(p["method"], p["amount"], p["status"]) for p in s["payments"]] == [
        ("cash", "500.00", "confirmed"),
        ("upi", "799.00", "confirmed"),
    ]
    assert s["payments"][1]["reference"] == "UPI123456"


@pytest.mark.parametrize("method", ["upi", "card"])
def test_electronic_payments_need_a_reference(
    client: TestClient, owner: dict[str, str], shop: dict[str, Any], method: str
) -> None:
    body = sale_body(shop, pay=None)
    for ref in (None, "", "   "):
        body["payments"] = [{"method": method, "amount": "1299.00", "reference": ref}]
        assert client.post("/sales", headers=owner, json=body).status_code == 422
    assert stock(client, owner, shop) == 10


def test_cannot_oversell_and_rolls_back_completely(
    client: TestClient, owner: dict[str, str], shop: dict[str, Any]
) -> None:
    body = sale_body(shop, qty=3, pay="3897.00")
    body["items"].append({"variant_id": shop["product"]["variants"][1]["id"], "quantity": 11})
    body["payments"][0]["amount"] = str(D("3897.00") + D("14289.00"))
    res = client.post("/sales", headers=owner, json=body)
    assert res.status_code == 409 and "Not enough stock" in res.json()["detail"]
    # The first line's stock movement was rolled back along with the rest.
    assert stock(client, owner, shop) == 10
    assert client.get("/sales", headers=owner, params={"store_id": shop["store"]}).json() == []


def test_idempotent_retry_returns_the_same_sale(
    client: TestClient, owner: dict[str, str], shop: dict[str, Any]
) -> None:
    body = sale_body(shop)
    first = client.post("/sales", headers=owner, json=body)
    again = client.post("/sales", headers=owner, json=body)
    assert (first.status_code, again.status_code) == (201, 200)
    assert again.json()["id"] == first.json()["id"] and again.json()["replayed"] is True
    assert again.json()["invoice_number"] == first.json()["invoice_number"]
    assert stock(client, owner, shop) == 9  # sold once, not twice
    assert len(client.get("/sales", headers=owner, params={"store_id": shop["store"]}).json()) == 1


def test_concurrent_duplicates_create_exactly_one_sale(
    client: TestClient, owner: dict[str, str], shop: dict[str, Any]
) -> None:
    body = sale_body(shop)

    def post(_: int) -> tuple[int, str]:
        with TestClient(app) as c:
            r = c.post("/sales", headers=owner, json=body)
            return r.status_code, r.json().get("id", r.text)

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(post, range(8)))
    assert all(code in (200, 201) for code, _ in results), results
    assert len({sale_id for _, sale_id in results}) == 1
    assert stock(client, owner, shop) == 9
    assert len(client.get("/sales", headers=owner, params={"store_id": shop["store"]}).json()) == 1


def test_idempotency_key_cannot_be_reused_for_another_store(
    client: TestClient, owner: dict[str, str], shop: dict[str, Any]
) -> None:
    body = sale_body(shop)
    client.post("/sales", headers=owner, json=body)
    other = client.post(
        "/stores", headers=owner, json={"code": "B2", "name": "B2", "state_code": "27"}
    ).json()
    res = client.post("/sales", headers=owner, json={**body, "store_id": other["id"]})
    assert res.status_code == 409


def test_invoice_numbers_are_sequential_and_gap_free_under_concurrency(
    client: TestClient, owner: dict[str, str], shop: dict[str, Any]
) -> None:
    def post(_: int) -> str:
        with TestClient(app) as c:
            r = c.post("/sales", headers=owner, json=sale_body(shop))
            assert r.status_code == 201, r.text
            return str(r.json()["invoice_number"])

    with ThreadPoolExecutor(max_workers=6) as pool:
        numbers = list(pool.map(post, range(10)))
    assert sorted(numbers) == [PREFIX + f"{n:05d}" for n in range(1, 11)]
    assert stock(client, owner, shop) == 0


def test_inter_state_sale_uses_igst(
    client: TestClient, owner: dict[str, str], shop: dict[str, Any]
) -> None:
    cust = client.post(
        "/customers", headers=owner, json={"name": "Far Away", "state_code": "29"}
    ).json()
    s = client.post("/sales", headers=owner, json=sale_body(shop, customer_id=cust["id"])).json()
    assert s["is_interstate"] is True and s["place_of_supply"] == "29"
    assert (s["cgst_total"], s["sgst_total"], s["igst_total"]) == ("0.00", "0.00", "61.86")
    same = client.post(
        "/customers", headers=owner, json={"name": "Local", "state_code": "27"}
    ).json()
    s2 = client.post("/sales", headers=owner, json=sale_body(shop, customer_id=same["id"])).json()
    assert s2["is_interstate"] is False and s2["igst_total"] == "0.00"


def test_discount_reduces_taxable_value_and_needs_permission_when_large(
    client: TestClient, owner: dict[str, str], shop: dict[str, Any], make_user: Any
) -> None:
    cashier = make_user("Cashier", "cash@example.com", store_ids=[shop["store"]])
    small = sale_body(shop, pay="1239.00")  # 1299.00 - 59.95 = 1239.05, rounded to the rupee
    small["items"][0]["discount"] = "59.95"
    s = client.post("/sales", headers=cashier, json=small).json()
    assert s["discount_total"] == "59.95" and s["items"][0]["line_total"] == "1239.05"
    assert (s["round_off"], s["grand_total"]) == ("-0.05", "1239.00")
    assert D(s["taxable_total"]) == (D("1239.05") / D("1.05")).quantize(D("0.01"))

    big = sale_body(shop, pay="1000.00")
    big["items"][0]["discount"] = "299.00"  # > 10% of the line
    denied = client.post("/sales", headers=cashier, json=big)
    assert denied.status_code == 403 and "sale:discount" in denied.json()["detail"]
    big["idempotency_key"] = str(uuid.uuid4())
    assert client.post("/sales", headers=owner, json=big).status_code == 201  # Owner holds it
    over = sale_body(shop, pay="0")
    over["items"][0]["discount"] = "5000.00"
    assert client.post("/sales", headers=owner, json=over).status_code == 422


def test_price_slab_selects_rate_by_net_price_and_basis_is_configurable(
    client: TestClient, owner: dict[str, str], store_id: str, make_product: Any, monkeypatch: Any
) -> None:
    # Test figures only: <=1000 -> 5%, >1000 -> 12%.
    low = _rate(client, owner, "5", name="Slabbed", max_unit_price="1000")
    _rate(client, owner, "12", name="Slabbed", min_unit_price="1000")
    p = make_product(price="1200.00", tax_rate_id=low)
    v = p["variants"][0]["id"]
    client.post(
        "/inventory/movements",
        headers=owner,
        json={"store_id": store_id, "variant_id": v, "kind": "opening", "quantity": 20},
    )

    def sell(discount: str, pay: str) -> dict[str, Any]:
        body = {
            "idempotency_key": str(uuid.uuid4()),
            "store_id": store_id,
            "items": [{"variant_id": v, "quantity": 1, "discount": discount}],
            "payments": [{"method": "cash", "amount": pay}],
        }
        res = client.post("/sales", headers=owner, json=body)
        assert res.status_code == 201, res.text
        return res.json()["items"][0]  # type: ignore[no-any-return]

    assert sell("0", "1200.00")["tax_rate"] == "12.00"
    assert sell("200", "1000.00")["tax_rate"] == "5.00"  # net 1000 -> "up to 1000"
    assert sell("199.99", "1000.00")["tax_rate"] == "12.00"  # net 1000.01 -> "above 1000"
    monkeypatch.setattr(get_settings(), "gst_slab_basis", "before_discount")
    assert sell("200", "1000.00")["tax_rate"] == "12.00"  # judged on the 1200 list price


def test_product_without_a_rate_or_with_no_rate_in_force_is_refused(
    client: TestClient, owner: dict[str, str], store_id: str, make_product: Any
) -> None:
    bare = make_product("Bare", price="500.00")
    future = make_product(
        "Future", price="500.00", tax_rate_id=_rate(client, owner, "5", effective_from="2099-01-01")
    )
    for p in (bare, future):
        v = p["variants"][0]["id"]
        client.post(
            "/inventory/movements",
            headers=owner,
            json={"store_id": store_id, "variant_id": v, "kind": "opening", "quantity": 3},
        )
        res = client.post(
            "/sales",
            headers=owner,
            json={
                "idempotency_key": str(uuid.uuid4()),
                "store_id": store_id,
                "items": [{"variant_id": v, "quantity": 1}],
                "payments": [{"method": "cash", "amount": "500.00"}],
            },
        )
        assert res.status_code == 422, res.text
        assert "GST" in res.json()["detail"]


def test_sale_snapshot_is_immune_to_later_product_edits(
    client: TestClient, owner: dict[str, str], shop: dict[str, Any]
) -> None:
    sale = client.post("/sales", headers=owner, json=sale_body(shop)).json()
    pid = shop["product"]["id"]
    client.patch(
        f"/products/{pid}",
        headers=owner,
        json={"name": "Renamed", "selling_price": "9999.00", "hsn_code": "1111"},
    )
    again = client.get(f"/sales/{sale['id']}", headers=owner).json()
    line = again["items"][0]
    assert (line["product_name"], line["unit_price"], line["hsn_code"]) == (
        "Classic Shirt",
        "1299.00",
        "6205",
    )
    assert again["grand_total"] == sale["grand_total"]


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE sales SET grand_total = 1",
        "DELETE FROM sales",
        "UPDATE sale_items SET unit_price = 1",
        "DELETE FROM sale_items",
        "UPDATE payments SET amount = 1",
        "DELETE FROM payments",
        "UPDATE gst_documents SET number = 'X'",
        "DELETE FROM gst_documents",
        "UPDATE stock_movements SET quantity_delta = 99",
        "DELETE FROM stock_movements",
    ],
)
def test_financial_records_are_immutable_in_the_database(
    client: TestClient, owner: dict[str, str], shop: dict[str, Any], sql: str
) -> None:
    client.post("/sales", headers=owner, json=sale_body(shop))
    with engine.connect() as conn, pytest.raises(DBAPIError, match="append-only"):
        conn.execute(text(sql))


def test_permissions_and_store_scoping(
    client: TestClient, owner: dict[str, str], shop: dict[str, Any], make_user: Any
) -> None:
    assert client.post("/sales", json=sale_body(shop)).status_code == 401
    other = client.post(
        "/stores", headers=owner, json={"code": "B2", "name": "B2", "state_code": "27"}
    ).json()
    elsewhere = make_user("Cashier", "far@example.com", store_ids=[other["id"]])
    assert client.post("/sales", headers=elsewhere, json=sale_body(shop)).status_code == 403
    client.post("/roles", headers=owner, json={"name": "Viewer", "permissions": ["product:read"]})
    role = next(
        r["id"] for r in client.get("/roles", headers=owner).json() if r["name"] == "Viewer"
    )
    client.post(
        "/users",
        headers=owner,
        json={
            "email": "v@example.com",
            "full_name": "V",
            "password": "user-password-1",
            "role_id": role,
            "store_ids": [shop["store"]],
        },
    )
    viewer = login(client, "v@example.com", "user-password-1")
    assert client.post("/sales", headers=viewer, json=sale_body(shop)).status_code == 403
    sale = client.post("/sales", headers=owner, json=sale_body(shop)).json()
    assert client.get(f"/sales/{sale['id']}", headers=viewer).status_code == 403
    assert client.get(f"/sales/{sale['id']}", headers=elsewhere).status_code == 403
    assert (
        client.get("/sales", headers=elsewhere, params={"store_id": shop["store"]}).status_code
        == 403
    )


def test_unknown_or_inactive_customer_and_variant(
    client: TestClient, owner: dict[str, str], shop: dict[str, Any]
) -> None:
    assert (
        client.post(
            "/sales", headers=owner, json=sale_body(shop, customer_id=str(uuid.uuid4()))
        ).status_code
        == 422
    )
    bad = sale_body(shop)
    bad["items"][0]["variant_id"] = str(uuid.uuid4())
    assert client.post("/sales", headers=owner, json=bad).status_code == 422
    client.patch(f"/products/{shop['product']['id']}", headers=owner, json={"is_active": False})
    assert client.post("/sales", headers=owner, json=sale_body(shop)).status_code == 409


def test_input_validation(client: TestClient, owner: dict[str, str], shop: dict[str, Any]) -> None:
    for patch in ({"items": []}, {"idempotency_key": "not-a-uuid"}):
        assert (
            client.post("/sales", headers=owner, json={**sale_body(shop), **patch}).status_code
            == 422
        )
    for qty in (0, -1, 10_001):
        assert (
            client.post("/sales", headers=owner, json=sale_body(shop, qty=qty)).status_code == 422
        )
    bad_pay = sale_body(shop)
    bad_pay["payments"] = [{"method": "cheque", "amount": "1299.00"}]
    assert client.post("/sales", headers=owner, json=bad_pay).status_code == 422
    bad_pay["payments"] = [{"method": "cash", "amount": "-5"}]
    assert client.post("/sales", headers=owner, json=bad_pay).status_code == 422


def test_stock_movement_references_the_sale(
    client: TestClient, owner: dict[str, str], shop: dict[str, Any]
) -> None:
    sale = client.post("/sales", headers=owner, json=sale_body(shop, qty=2, pay="2598.00")).json()
    with SessionLocal() as db:
        rows = db.execute(
            text(
                "SELECT movement_type, quantity_delta, reference_type, reference_id "
                "FROM stock_movements WHERE movement_type='sale'"
            )
        ).all()
    assert [(r[0], r[1], r[2], str(r[3])) for r in rows] == [("sale", -2, "sale", sale["id"])]


def test_invoice_pdf(client: TestClient, owner: dict[str, str], shop: dict[str, Any]) -> None:
    sale = client.post("/sales", headers=owner, json=sale_body(shop)).json()
    res = client.get(f"/sales/{sale['id']}/invoice.pdf", headers=owner)
    assert res.status_code == 200 and res.headers["content-type"] == "application/pdf"
    assert res.content.startswith(b"%PDF") and res.content.rstrip().endswith(b"%%EOF")
    assert sale["invoice_number"].replace("/", "-") in res.headers["content-disposition"]
    assert client.get(f"/sales/{uuid.uuid4()}/invoice.pdf", headers=owner).status_code == 404


def test_sale_list_filters_by_day(
    client: TestClient, owner: dict[str, str], shop: dict[str, Any]
) -> None:
    client.post("/sales", headers=owner, json=sale_body(shop))
    today = datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat()
    on_day = client.get(
        "/sales", headers=owner, params={"store_id": shop["store"], "day": today}
    ).json()
    assert len(on_day) == 1 and on_day[0]["invoice_number"] == PREFIX + "00001"
    assert (
        client.get(
            "/sales", headers=owner, params={"store_id": shop["store"], "day": "2020-01-01"}
        ).json()
        == []
    )


def test_sale_is_audited(client: TestClient, owner: dict[str, str], shop: dict[str, Any]) -> None:
    client.post("/sales", headers=owner, json=sale_body(shop))
    logs = client.get("/audit-logs", headers=owner, params={"entity_type": "sale"}).json()
    assert logs[0]["action"] == "sale.created" and logs[0]["after"]["invoice"] == PREFIX + "00001"


def test_quote_predicts_the_sale_exactly_and_changes_nothing(
    client: TestClient, owner: dict[str, str], shop: dict[str, Any]
) -> None:
    items = [
        {"variant_id": shop["variant"], "quantity": 3, "discount": "50.00"},
        {"variant_id": shop["product"]["variants"][1]["id"], "quantity": 1},
    ]
    q = client.post("/sales/quote", headers=owner, json={"store_id": shop["store"], "items": items})
    assert q.status_code == 200, q.text
    quote = q.json()
    # Pricing a basket must not touch stock, invoice numbers, or the sales table.
    assert stock(client, owner, shop) == 10
    assert client.get("/sales", headers=owner, params={"store_id": shop["store"]}).json() == []

    body = {
        "idempotency_key": str(uuid.uuid4()),
        "store_id": shop["store"],
        "items": items,
        "payments": [{"method": "cash", "amount": quote["grand_total"]}],
    }
    sale = client.post("/sales", headers=owner, json=body)
    assert sale.status_code == 201, sale.text
    s = sale.json()
    for field in (
        "discount_total",
        "taxable_total",
        "cgst_total",
        "sgst_total",
        "igst_total",
        "round_off",
        "grand_total",
        "place_of_supply",
    ):
        assert s[field] == quote[field], field
    assert [ln["line_total"] for ln in quote["lines"]] == [i["line_total"] for i in s["items"]]
    assert s["invoice_number"] == PREFIX + "00001"  # the quote did not consume a number


def test_quote_applies_the_same_rules_as_a_sale(
    client: TestClient, owner: dict[str, str], shop: dict[str, Any], make_user: Any
) -> None:
    cashier = make_user("Cashier", "cash@example.com", store_ids=[shop["store"]])
    big = {
        "store_id": shop["store"],
        "items": [{"variant_id": shop["variant"], "quantity": 1, "discount": "500.00"}],
    }
    assert (
        client.post("/sales/quote", headers=cashier, json=big).status_code == 403
    )  # discount rule
    bare = {"store_id": shop["store"], "items": [{"variant_id": str(uuid.uuid4()), "quantity": 1}]}
    assert client.post("/sales/quote", headers=owner, json=bare).status_code == 422
    assert client.post("/sales/quote", json=big).status_code == 401
    other = client.post(
        "/stores", headers=owner, json={"code": "B2", "name": "B2", "state_code": "27"}
    ).json()
    elsewhere = make_user("Cashier", "far@example.com", store_ids=[other["id"]])
    assert (
        client.post(
            "/sales/quote",
            headers=elsewhere,
            json={**big, "items": [{"variant_id": shop["variant"], "quantity": 1}]},
        ).status_code
        == 403
    )


def test_invoice_time_is_shown_in_indian_time_regardless_of_server_timezone() -> None:
    from datetime import UTC

    from app.services.invoice_pdf import invoice_timestamp

    # 19:37 UTC on 20 Nov is already 01:07 on 21 Nov in India: the date must roll over.
    assert invoice_timestamp(datetime(2026, 11, 20, 19, 37, tzinfo=UTC)) == "21 Nov 2026, 01:07 AM"
    assert invoice_timestamp(datetime(2026, 3, 31, 18, 29, tzinfo=UTC)) == "31 Mar 2026, 11:59 PM"
    assert invoice_timestamp(datetime(2026, 3, 31, 18, 30, tzinfo=UTC)) == "01 Apr 2026, 12:00 AM"


def test_sale_lines_keep_the_order_they_were_entered(
    client: TestClient, owner: dict[str, str], store_id: str, make_product: Any
) -> None:
    rate = _rate(client, owner, "5")
    names = ["Zebra Tee", "Apple Tee", "Mango Tee", "Banana Tee", "Cherry Tee", "Date Tee"]
    variants = []
    for n in names:
        v = make_product(n, price="100.00", tax_rate_id=rate)["variants"][0]["id"]
        client.post(
            "/inventory/movements",
            headers=owner,
            json={"store_id": store_id, "variant_id": v, "kind": "opening", "quantity": 5},
        )
        variants.append(v)
    body = {
        "idempotency_key": str(uuid.uuid4()),
        "store_id": store_id,
        "items": [{"variant_id": v, "quantity": 1} for v in variants],
        "payments": [{"method": "cash", "amount": "600.00"}],
    }
    sale = client.post("/sales", headers=owner, json=body).json()
    assert [i["product_name"] for i in sale["items"]] == names  # not alphabetical, not random
    again = client.get(f"/sales/{sale['id']}", headers=owner).json()
    assert [i["product_name"] for i in again["items"]] == names
