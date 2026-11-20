import csv
import io
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app.db.session import SessionLocal
from app.models import Payment, Sale, SaleItem
from app.services import gst
from tests.conftest import login

IST = ZoneInfo("Asia/Kolkata")


def ist(y: int, m: int, d: int, h: int = 12, mi: int = 0) -> datetime:
    return datetime(y, m, d, h, mi, tzinfo=IST)


def insert_sale(
    client: TestClient,
    owner: dict[str, str],
    variant: dict[str, Any],
    product_name: str,
    when: datetime,
    qty: int = 1,
    price: str = "1000.00",
    cost: str = "400.00",
    rate: str = "5",
    method: str = "cash",
    interstate: bool = False,
    store: str | None = None,
) -> None:
    """Writes a historical sale straight to the database (the API can only sell 'now')."""
    me = client.get("/auth/me", headers=owner).json()
    store_id = store or client.get("/stores", headers=owner).json()[0]["id"]
    gross = D(price) * qty
    t = gst.split_inclusive(gross, D(rate), interstate)
    total, off = gst.round_to_rupee(gross)
    with SessionLocal() as db:
        sale = Sale(
            business_id=uuid.UUID(me["business_id"]), store_id=uuid.UUID(store_id),
            user_id=uuid.UUID(me["id"]), idempotency_key=uuid.uuid4(), sold_at=when,
            place_of_supply="29" if interstate else "27", is_interstate=interstate,
            discount_total=D("0"), taxable_total=t.taxable, cgst_total=t.cgst, sgst_total=t.sgst,
            igst_total=t.igst, round_off=off, grand_total=total,
        )  # fmt: skip
        db.add(sale)
        db.flush()
        db.add(SaleItem(
            sale_id=sale.id, variant_id=uuid.UUID(variant["id"]), product_name=product_name,
            variant_label="M", sku=variant["sku"], hsn_code="6205", line_no=1, quantity=qty,
            unit_price=D(price), discount=D("0"), unit_cost=D(cost), tax_rate=D(rate),
            taxable_value=t.taxable, cgst=t.cgst, sgst=t.sgst, igst=t.igst, line_total=t.gross,
        ))  # fmt: skip
        db.add(
            Payment(
                business_id=sale.business_id,
                sale_id=sale.id,
                method=method,
                amount=total,
                status="confirmed",
                reference=None if method == "cash" else "R1",
            )
        )
        db.commit()


@pytest.fixture
def prods(client: TestClient, owner: dict[str, str], make_product: Any) -> dict[str, Any]:
    a = make_product("Alpha Shirt", price="1000.00")["variants"][0]
    b = make_product("Beta Jeans", price="2000.00")["variants"][0]
    return {"a": a, "b": b}


def rep(client: TestClient, headers: dict[str, str], name: str, **params: Any) -> Any:
    res = client.get(f"/reports/{name}", headers=headers, params=params)
    assert res.status_code == 200, res.text
    return res.json()


def test_sales_summary_matches_known_totals(
    client: TestClient, owner: dict[str, str], prods: dict[str, Any]
) -> None:
    a = prods["a"]
    insert_sale(client, owner, a, "Alpha Shirt", ist(2026, 11, 2), qty=2, method="cash")
    insert_sale(client, owner, a, "Alpha Shirt", ist(2026, 11, 2, 18), qty=1, method="upi")
    r = rep(client, owner, "sales", **{"from": "2026-11-01", "to": "2026-11-03", "group": "day"})
    by = {row["period"]: row for row in r["rows"]}
    assert list(by) == ["2026-11-01", "2026-11-02", "2026-11-03"]  # empty days are zero, not gaps
    assert by["2026-11-01"]["orders"] == 0 and by["2026-11-01"]["total"] == "0.00"
    d = by["2026-11-02"]
    # 3 units at 1000.00 incl. 5%: taxable 2857.14 (952.38 + 1904.76), GST 142.86, cost 3 x 400.
    assert (d["orders"], d["items"], d["total"]) == (2, 3, "3000.00")
    assert D(d["taxable"]) + D(d["gst"]) == D("3000.00")
    assert (d["cost"], d["margin"]) == ("1200.00", str(D(d["taxable"]) - D("1200.00")))
    assert r["totals"]["orders"] == 2 and r["totals"]["total"] == "3000.00"
    assert r["meta"]["payments"] == {"cash": "2000.00", "upi": "1000.00"}
    assert r["meta"]["average_order_value"] == "1500.00"
    assert r["meta"]["lines_without_cost"] == 0


def test_days_roll_over_at_midnight_india_time_not_utc(
    client: TestClient, owner: dict[str, str], prods: dict[str, Any]
) -> None:
    a = prods["a"]
    # 2026-11-01 19:00 UTC is 00:30 on 2 Nov in India, so it belongs to 2 Nov.
    insert_sale(client, owner, a, "Alpha", datetime(2026, 11, 1, 19, 0, tzinfo=UTC))
    # 2026-11-01 18:29 UTC is 23:59 on 1 Nov in India.
    insert_sale(client, owner, a, "Alpha", datetime(2026, 11, 1, 18, 29, tzinfo=UTC))
    r = rep(client, owner, "sales", **{"from": "2026-11-01", "to": "2026-11-02", "group": "day"})
    assert [(x["period"], x["orders"]) for x in r["rows"]] == [("2026-11-01", 1), ("2026-11-02", 1)]
    # The range is inclusive of the whole last day in India time.
    only_first = rep(client, owner, "sales", **{"from": "2026-11-01", "to": "2026-11-01"})
    assert only_first["totals"]["orders"] == 1


def test_week_and_month_grouping(
    client: TestClient, owner: dict[str, str], prods: dict[str, Any]
) -> None:
    a = prods["a"]
    for when in (
        ist(2026, 10, 30),
        ist(2026, 11, 1),
        ist(2026, 11, 2),
        ist(2026, 11, 8),
        ist(2026, 11, 9),
    ):
        insert_sale(client, owner, a, "Alpha", when)
    # 2026-11-01 is a Sunday and 2026-11-02 a Monday: weeks run Monday to Sunday.
    wk = rep(client, owner, "sales", **{"from": "2026-10-26", "to": "2026-11-09", "group": "week"})
    assert [(x["period"], x["orders"]) for x in wk["rows"]] == [
        ("Week of 2026-10-26", 2),
        ("Week of 2026-11-02", 2),
        ("Week of 2026-11-09", 1),
    ]
    mo = rep(client, owner, "sales", **{"from": "2026-10-01", "to": "2026-11-30", "group": "month"})
    assert [(x["period"], x["orders"]) for x in mo["rows"]] == [("2026-10", 1), ("2026-11", 4)]
    assert sum(x["orders"] for x in wk["rows"]) == wk["totals"]["orders"] == 5


def test_missing_cost_is_flagged_so_margin_is_not_overstated(
    client: TestClient, owner: dict[str, str], prods: dict[str, Any]
) -> None:
    insert_sale(client, owner, prods["a"], "Alpha", ist(2026, 11, 2), cost="0.00")
    insert_sale(client, owner, prods["a"], "Alpha", ist(2026, 11, 2), cost="400.00")
    r = rep(client, owner, "sales", **{"from": "2026-11-02", "to": "2026-11-02"})
    assert r["meta"]["lines_without_cost"] == 1


def test_gst_summary_groups_by_rate_and_ties_to_sales(
    client: TestClient, owner: dict[str, str], prods: dict[str, Any]
) -> None:
    insert_sale(client, owner, prods["a"], "Alpha", ist(2026, 11, 2), rate="5")
    insert_sale(client, owner, prods["b"], "Beta", ist(2026, 11, 2), price="2000.00", rate="12")
    insert_sale(
        client,
        owner,
        prods["b"],
        "Beta",
        ist(2026, 11, 3),
        price="2000.00",
        rate="12",
        interstate=True,
    )
    p = {"from": "2026-11-01", "to": "2026-11-30"}
    g = rep(client, owner, "gst", **p)
    by = {x["rate"]: x for x in g["rows"]}
    assert set(by) == {"5.00", "12.00"} and by["12.00"]["lines"] == 2
    assert by["12.00"]["igst"] != "0.00" and by["12.00"]["cgst"] != "0.00"
    s = rep(client, owner, "sales", **p)
    assert g["totals"]["taxable"] == s["totals"]["taxable"]
    gst_total = D(g["totals"]["cgst"]) + D(g["totals"]["sgst"]) + D(g["totals"]["igst"])
    assert gst_total == D(s["totals"]["gst"])


def test_top_products_rank_by_quantity_or_revenue(
    client: TestClient, owner: dict[str, str], prods: dict[str, Any]
) -> None:
    insert_sale(client, owner, prods["a"], "Alpha Shirt", ist(2026, 11, 2), qty=5, price="1000.00")
    insert_sale(client, owner, prods["b"], "Beta Jeans", ist(2026, 11, 2), qty=2, price="2000.00")
    p = {"from": "2026-11-01", "to": "2026-11-30"}
    by_qty = rep(client, owner, "top-products", rank="quantity", **p)["rows"]
    assert [(r["product"], r["quantity"]) for r in by_qty] == [
        ("Alpha Shirt", 5),
        ("Beta Jeans", 2),
    ]
    by_rev = rep(client, owner, "top-products", rank="revenue", **p)["rows"]
    assert [r["product"] for r in by_rev] == ["Alpha Shirt", "Beta Jeans"]  # 5000 vs 4000
    insert_sale(client, owner, prods["b"], "Beta Jeans", ist(2026, 11, 3), qty=2, price="2000.00")
    by_rev = rep(client, owner, "top-products", rank="revenue", **p)["rows"]
    assert [r["product"] for r in by_rev] == ["Beta Jeans", "Alpha Shirt"]  # 8000 vs 5000
    assert len(rep(client, owner, "top-products", limit=1, **p)["rows"]) == 1


def test_stock_report_values_and_filters(
    client: TestClient, owner: dict[str, str], store_id: str, make_product: Any
) -> None:
    p = make_product("Alpha Shirt", price="1000.00", cost_price="400.00")
    a, b = p["variants"]
    client.post(
        "/inventory/movements",
        headers=owner,
        json={"store_id": store_id, "variant_id": a["id"], "kind": "opening", "quantity": 10},
    )
    client.put(
        "/inventory/reorder-level",
        headers=owner,
        json={"store_id": store_id, "variant_id": a["id"], "reorder_level": 12},
    )
    r = rep(client, owner, "stock")
    assert len(r["rows"]) == 2  # unstocked variants are listed with 0
    assert r["totals"]["quantity"] == 10
    assert (r["totals"]["cost_value"], r["totals"]["retail_value"]) == ("4000.00", "10000.00")
    low = rep(client, owner, "stock", low_only=True)
    assert [x["sku"] for x in low["rows"]] == [a["sku"]] and low["rows"][0]["status"] == "Low"
    assert low["meta"]["low_stock_lines"] == 1
    status = {x["sku"]: x["status"] for x in r["rows"]}
    assert status == {a["sku"]: "Low", b["sku"]: "Out"}  # never-stocked is Out, not Low
    nonzero = rep(client, owner, "stock", hide_zero=True)
    assert [x["sku"] for x in nonzero["rows"]] == [a["sku"]]


def test_purchases_summary_counts_received_bills_only(
    client: TestClient, owner: dict[str, str], store_id: str, prods: dict[str, Any]
) -> None:
    s1 = client.post("/suppliers", headers=owner, json={"name": "Mills A"}).json()["id"]
    s2 = client.post("/suppliers", headers=owner, json={"name": "Mills B"}).json()["id"]

    def bill(sup: str, no: str, cost: str, day: str, receive: bool) -> None:
        pid = client.post(
            "/purchases",
            headers=owner,
            json={
                "store_id": store_id,
                "supplier_id": sup,
                "bill_number": no,
                "bill_date": day,
                "items": [{"variant_id": prods["a"]["id"], "quantity": 10, "unit_cost": cost}],
            },
        ).json()["id"]
        if receive:
            assert client.post(f"/purchases/{pid}/receive", headers=owner).status_code == 200

    bill(s1, "1", "100.00", "2026-11-02", True)
    bill(s1, "2", "50.00", "2026-11-09", True)
    bill(s2, "3", "10.00", "2026-11-02", True)
    bill(s2, "4", "999.00", "2026-11-02", False)  # draft: must not count
    p = {"from": "2026-11-01", "to": "2026-11-30"}
    by_sup = rep(client, owner, "purchases", breakdown="supplier", **p)
    assert [(r["label"], r["bills"], r["total"]) for r in by_sup["rows"]] == [
        ("Mills A", 2, "1500.00"),
        ("Mills B", 1, "100.00"),
    ]
    by_week = rep(client, owner, "purchases", breakdown="period", group="week", **p)
    assert by_week["totals"]["total"] == "1600.00" and by_week["totals"]["bills"] == 3


def test_overview_for_the_home_page(
    client: TestClient, owner: dict[str, str], store_id: str, prods: dict[str, Any]
) -> None:
    today = datetime.now(IST)
    insert_sale(client, owner, prods["a"], "Alpha", today, qty=2)
    insert_sale(client, owner, prods["a"], "Alpha", today - timedelta(days=3))
    client.put(
        "/inventory/reorder-level",
        headers=owner,
        json={"store_id": store_id, "variant_id": prods["a"]["id"], "reorder_level": 5},
    )
    o = client.get("/reports/overview", headers=owner).json()
    assert (o["orders"], o["revenue"], o["low_stock_items"], o["active_products"]) == (
        1,
        "2000.00",
        1,
        2,
    )
    assert o["date"] == today.date().isoformat()


def test_reports_need_permission_and_respect_store_scope(
    client: TestClient, owner: dict[str, str], store_id: str, prods: dict[str, Any], make_user: Any
) -> None:
    other = client.post(
        "/stores", headers=owner, json={"code": "B2", "name": "B2", "state_code": "27"}
    ).json()
    insert_sale(client, owner, prods["a"], "Alpha", ist(2026, 11, 2), store=store_id)
    insert_sale(client, owner, prods["a"], "Alpha", ist(2026, 11, 2), store=other["id"], qty=3)
    p = {"from": "2026-11-01", "to": "2026-11-30"}
    assert rep(client, owner, "sales", **p)["totals"]["orders"] == 2  # owner sees every store
    assert rep(client, owner, "sales", store_id=other["id"], **p)["totals"]["items"] == 3

    cashier = make_user("Cashier", "cash@example.com", store_ids=[store_id])
    for name in ("sales", "gst", "stock", "purchases", "top-products", "overview"):
        assert client.get(f"/reports/{name}", headers=cashier).status_code == 403, name
    mgr = make_user("Manager", "mgr@example.com", store_ids=[other["id"]])
    mine = rep(client, mgr, "sales", **p)
    assert mine["totals"]["orders"] == 1 and mine["totals"]["items"] == 3  # only their own store
    assert (
        client.get("/reports/sales", headers=mgr, params={"store_id": store_id, **p}).status_code
        == 403
    )
    assert client.get("/reports/sales", params=p).status_code == 401


def test_other_businesses_never_leak_into_reports(
    client: TestClient, owner: dict[str, str], prods: dict[str, Any]
) -> None:
    from app.models import Business, Store

    with SessionLocal() as db:
        biz = Business(name="Other", state_code="29")
        db.add(biz)
        db.flush()
        db.add(Store(business_id=biz.id, code="OT", name="Other", state_code="29"))
        db.commit()
    insert_sale(client, owner, prods["a"], "Alpha", ist(2026, 11, 2))
    r = rep(client, owner, "sales", **{"from": "2026-11-01", "to": "2026-11-30"})
    assert r["totals"]["orders"] == 1
    assert {x["store"] for x in rep(client, owner, "stock")["rows"]} == {"Main Store"}


def test_validation(client: TestClient, owner: dict[str, str]) -> None:
    def status(**params: Any) -> int:
        return client.get("/reports/sales", headers=owner, params=params).status_code

    assert status(**{"from": "2026-11-10", "to": "2026-11-01"}) == 422
    assert status(**{"from": "2025-01-01", "to": "2026-11-01"}) == 422  # over 400 days
    assert status(group="year") == 422
    assert status(**{"from": "not-a-date"}) == 422
    assert client.get("/reports/nonsense", headers=owner).status_code == 422
    assert status() == 200  # defaults to the last 30 days


def _rows(res: Any) -> list[list[str]]:
    return list(csv.reader(io.StringIO(res.content.decode("utf-8-sig"))))


def test_csv_export_matches_the_report(
    client: TestClient, owner: dict[str, str], prods: dict[str, Any]
) -> None:
    insert_sale(client, owner, prods["a"], "Alpha Shirt", ist(2026, 11, 2), qty=2)
    p = {"from": "2026-11-02", "to": "2026-11-02"}
    res = client.get("/reports/sales.csv", headers=owner, params=p)
    assert res.status_code == 200 and res.headers["content-type"].startswith("text/csv")
    assert (
        res.headers["content-disposition"]
        == 'attachment; filename="sales-2026-11-02_to_2026-11-02.csv"'
    )
    assert res.content.startswith(b"\xef\xbb\xbf")  # BOM so Excel reads it as UTF-8
    rows = _rows(res)
    assert rows[0] == ["Sales summary"] and "2026-11-02" in rows[1][0]
    assert rows[3][0] == "Period" and rows[3][1] == "Orders"
    assert rows[4][:3] == ["2026-11-02", "1", "2"] and rows[4][6] == "2000.00"
    assert rows[5][0] == "Total" and rows[5][6] == "2000.00"


def test_csv_neutralises_spreadsheet_formulas(
    client: TestClient, owner: dict[str, str], make_product: Any
) -> None:
    for name in ('=HYPERLINK("http://evil","x")', "+SUM(1,1)", "-2+3", "@cmd"):
        make_product(name, price="10.00")
    body = _rows(client.get("/reports/stock.csv", headers=owner))
    products = {row[1] for row in body[4:-1]}
    assert products == {'\'=HYPERLINK("http://evil","x")', "'+SUM(1,1)", "'-2+3", "'@cmd"}
    # Numbers stay numbers: a negative money value is not mangled.
    assert not any(cell.startswith("'") for row in body[4:-1] for cell in row[4:])


@pytest.mark.parametrize("name", ["sales", "gst", "top-products", "stock", "purchases"])
def test_every_report_exports_csv_and_pdf(
    client: TestClient, owner: dict[str, str], prods: dict[str, Any], name: str
) -> None:
    insert_sale(client, owner, prods["a"], "Alpha & <Co>", ist(2026, 11, 2))
    p = {"from": "2026-11-01", "to": "2026-11-30"}
    assert client.get(f"/reports/{name}.csv", headers=owner, params=p).status_code == 200
    pdf = client.get(f"/reports/{name}.pdf", headers=owner, params=p)
    assert pdf.status_code == 200 and pdf.headers["content-type"] == "application/pdf"
    assert pdf.content.startswith(b"%PDF") and pdf.content.rstrip().endswith(b"%%EOF")


def test_exports_are_permission_gated(client: TestClient, make_user: Any) -> None:
    cashier = make_user("Cashier", "cash@example.com")
    assert client.get("/reports/sales.csv", headers=cashier).status_code == 403
    assert client.get("/reports/sales.pdf", headers=cashier).status_code == 403


def test_reports_are_consistent_after_a_real_sale_through_the_api(
    client: TestClient, owner: dict[str, str], store_id: str, make_product: Any
) -> None:
    rate = client.post(
        "/tax-rates",
        headers=owner,
        json={"name": "R5", "rate": "5", "effective_from": "2020-01-01"},
    ).json()["id"]
    v = make_product(price="1299.00", cost_price="700.00", tax_rate_id=rate)["variants"][0]["id"]
    client.post(
        "/inventory/movements",
        headers=owner,
        json={"store_id": store_id, "variant_id": v, "kind": "opening", "quantity": 5},
    )
    sale = client.post(
        "/sales",
        headers=owner,
        json={
            "idempotency_key": str(uuid.uuid4()),
            "store_id": store_id,
            "items": [{"variant_id": v, "quantity": 2}],
            "payments": [{"method": "upi", "amount": "2598.00", "reference": "U1"}],
        },
    ).json()
    today = datetime.now(IST).date().isoformat()
    r = rep(client, owner, "sales", **{"from": today, "to": today})
    assert (
        r["totals"]["total"] == sale["grand_total"]
        and r["totals"]["taxable"] == sale["taxable_total"]
    )
    assert r["totals"]["cost"] == "1400.00" and r["meta"]["payments"] == {"upi": "2598.00"}
    stock = rep(client, owner, "stock")
    assert stock["totals"]["quantity"] == 3
    assert login  # imported for parity with other test modules


# ---- overview (the front page) ----
@pytest.mark.parametrize(
    ("rng", "today", "expected"),
    [
        # Saturday 21 Nov 2026
        (
            "today",
            date(2026, 11, 21),
            (date(2026, 11, 21), date(2026, 11, 21), date(2026, 11, 20), date(2026, 11, 20)),
        ),
        # Week = Monday..today; compared with last week over the same elapsed days (Mon..Sat).
        (
            "week",
            date(2026, 11, 21),
            (date(2026, 11, 16), date(2026, 11, 21), date(2026, 11, 9), date(2026, 11, 14)),
        ),
        # On a Monday the week has one day so far, and so does the comparison.
        (
            "week",
            date(2026, 11, 16),
            (date(2026, 11, 16), date(2026, 11, 16), date(2026, 11, 9), date(2026, 11, 9)),
        ),
        (
            "month",
            date(2026, 11, 21),
            (date(2026, 11, 1), date(2026, 11, 21), date(2026, 10, 1), date(2026, 10, 21)),
        ),
        # 31 March compared with February: the previous window is clamped to February's end.
        (
            "month",
            date(2026, 3, 31),
            (date(2026, 3, 1), date(2026, 3, 31), date(2026, 2, 1), date(2026, 2, 28)),
        ),
        (
            "month",
            date(2026, 1, 15),
            (date(2026, 1, 1), date(2026, 1, 15), date(2025, 12, 1), date(2025, 12, 15)),
        ),
    ],
)
def test_period_bounds(rng: Any, today: date, expected: tuple[date, date, date, date]) -> None:
    from app.services.reports import period_bounds

    assert period_bounds(rng, today) == expected


def test_growth_percentages() -> None:
    from app.services.reports import _growth

    assert _growth(D("150"), D("100")) == "50.0"
    assert _growth(D("50"), D("100")) == "-50.0"
    assert _growth(D("100"), D("100")) == "0.0"
    assert _growth(D("100"), D("0")) is None  # nothing to compare with: no made-up percentage
    assert _growth(3, 2) == "50.0"


def test_overview_today_compares_with_yesterday_and_charts_by_hour(
    client: TestClient, owner: dict[str, str], prods: dict[str, Any]
) -> None:
    now = datetime.now(IST)
    day = now.replace(hour=10, minute=15, second=0, microsecond=0)
    insert_sale(client, owner, prods["a"], "Alpha", day, price="1000.00")
    insert_sale(client, owner, prods["a"], "Alpha", day.replace(minute=45), price="1000.00")
    insert_sale(client, owner, prods["a"], "Alpha", day - timedelta(days=1), price="1000.00")
    o = client.get("/reports/overview", headers=owner, params={"range": "today"}).json()
    assert (o["orders"], o["revenue"]) == (2, "2000.00")
    assert (o["orders_previous"], o["revenue_previous"]) == (1, "1000.00")
    assert o["revenue_growth"] == "100.0" and o["orders_growth"] == "100.0"
    s = o["series"]
    assert s["kind"] == "hour"
    pts = {p["label"]: p["total"] for p in s["points"]}
    assert pts["10 AM"] == "2000.00" and pts["9 AM"] == "0.00" and pts["9 PM"] == "0.00"
    assert [p["label"] for p in s["points"]][0] == "9 AM" and len(s["points"]) == 13  # 9 AM..9 PM


def test_hourly_chart_widens_for_sales_outside_trading_hours(
    client: TestClient, owner: dict[str, str], prods: dict[str, Any]
) -> None:
    now = datetime.now(IST)
    insert_sale(client, owner, prods["a"], "Alpha", now.replace(hour=6, minute=30))
    insert_sale(client, owner, prods["a"], "Alpha", now.replace(hour=23, minute=30))
    labels = [
        p["label"]
        for p in client.get("/reports/overview", headers=owner).json()["series"]["points"]
    ]
    assert labels[0] == "6 AM" and labels[-1] == "11 PM"  # nothing sold is hidden


def test_overview_week_and_month_chart_by_day(
    client: TestClient, owner: dict[str, str], prods: dict[str, Any]
) -> None:
    now = datetime.now(IST)
    today = now.date()
    insert_sale(client, owner, prods["a"], "Alpha", now.replace(hour=12))
    insert_sale(
        client, owner, prods["a"], "Alpha", now.replace(hour=12) - timedelta(days=7)
    )  # last week
    wk = client.get("/reports/overview", headers=owner, params={"range": "week"}).json()
    assert wk["series"]["kind"] == "day"
    assert len(wk["series"]["points"]) == today.weekday() + 1  # Monday..today
    assert wk["series"]["points"][-1]["label"] == today.isoformat()
    assert (wk["orders"], wk["orders_previous"], wk["revenue_growth"]) == (1, 1, "0.0")

    first_of_month = today.replace(day=1)
    prev_month_first = (first_of_month - timedelta(days=1)).replace(day=1)
    insert_sale(
        client,
        owner,
        prods["b"],
        "Beta",
        datetime.combine(prev_month_first, now.time(), tzinfo=IST),
        price="2000.00",
    )
    mo = client.get("/reports/overview", headers=owner, params={"range": "month"}).json()
    assert (
        len(mo["series"]["points"]) == today.day
        and mo["series"]["points"][0]["label"] == first_of_month.isoformat()
    )
    assert mo["orders_previous"] == 1 and mo["revenue_previous"] == "2000.00"
    assert mo["revenue_growth"] == f"{(D(mo['revenue']) - D('2000')) / D('2000') * 100:.1f}"


def test_overview_without_a_previous_period_gives_no_growth_figure(
    client: TestClient, owner: dict[str, str], prods: dict[str, Any]
) -> None:
    insert_sale(client, owner, prods["a"], "Alpha", datetime.now(IST).replace(hour=12))
    o = client.get("/reports/overview", headers=owner, params={"range": "today"}).json()
    assert (
        o["revenue_previous"] == "0.00"
        and o["revenue_growth"] is None
        and o["orders_growth"] is None
    )


def test_overview_scopes_to_a_store_and_validates_the_range(
    client: TestClient, owner: dict[str, str], store_id: str, prods: dict[str, Any]
) -> None:
    other = client.post(
        "/stores", headers=owner, json={"code": "B2", "name": "B2", "state_code": "27"}
    ).json()
    noon = datetime.now(IST).replace(hour=12)
    insert_sale(client, owner, prods["a"], "Alpha", noon, store=store_id)
    insert_sale(client, owner, prods["a"], "Alpha", noon, store=other["id"], qty=3)
    everything = client.get("/reports/overview", headers=owner).json()
    assert everything["orders"] == 2
    only_other = client.get(
        "/reports/overview", headers=owner, params={"store_id": other["id"]}
    ).json()
    assert (only_other["orders"], only_other["revenue"]) == (1, "3000.00")
    assert (
        client.get("/reports/overview", headers=owner, params={"range": "year"}).status_code == 422
    )
    assert (
        client.get(
            "/reports/overview", headers=owner, params={"store_id": str(uuid.uuid4())}
        ).status_code
        == 403
    )


def test_inventory_alerts_can_be_sorted_lowest_stock_first(
    client: TestClient, owner: dict[str, str], store_id: str, make_product: Any
) -> None:
    variants = [make_product(n, price="100.00")["variants"][0]["id"] for n in ("Aaa", "Bbb", "Ccc")]
    for v, qty in zip(variants, (30, 5, 12), strict=True):
        client.post(
            "/inventory/movements",
            headers=owner,
            json={"store_id": store_id, "variant_id": v, "kind": "opening", "quantity": qty},
        )
        client.put(
            "/inventory/reorder-level",
            headers=owner,
            json={"store_id": store_id, "variant_id": v, "reorder_level": 40},
        )
    params = {"store_id": store_id, "low_stock": True, "limit": 2}
    by_stock = client.get("/inventory", headers=owner, params={**params, "sort": "stock"}).json()
    assert [r["quantity"] for r in by_stock] == [5, 12]  # the most urgent first, capped at 2
    by_name = client.get("/inventory", headers=owner, params=params).json()
    assert [r["product_name"] for r in by_name] == ["Aaa", "Bbb"]
    assert (
        client.get("/inventory", headers=owner, params={**params, "sort": "price"}).status_code
        == 422
    )
