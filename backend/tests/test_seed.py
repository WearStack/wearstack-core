from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.config import get_settings
from app.db.session import SessionLocal, engine
from app.seed_demo import PASSWORD, main, seed
from tests.conftest import login


def scalar(sql: str) -> Any:
    with engine.connect() as conn:
        return conn.execute(text(sql)).scalar()


def test_seed_builds_a_consistent_demo_shop_and_refuses_to_run_twice(
    client: TestClient, monkeypatch: Any
) -> None:
    with SessionLocal() as db:
        result = seed(db)
    assert int(result["sales"]) > 100

    # Same invariants as real use, because the seed goes through the real code paths.
    assert (
        scalar("""SELECT count(*) FROM inventory i WHERE i.quantity <> (
        SELECT coalesce(sum(quantity_delta), 0) FROM stock_movements m
        WHERE m.variant_id = i.variant_id AND m.store_id = i.store_id)""")
        == 0
    )
    assert scalar("SELECT count(*) FROM inventory WHERE quantity < 0") == 0
    assert (
        scalar("""SELECT count(*) FROM sales s WHERE s.grand_total <>
        (SELECT coalesce(sum(amount), 0) FROM payments p WHERE p.sale_id = s.id)""")
        == 0
    )
    assert (
        scalar("""SELECT count(*) FROM (SELECT store_id, financial_year, count(*) c,
        max(split_part(number, '/', 3)::int) m FROM gst_documents GROUP BY 1, 2) t
        WHERE c <> m""")
        == 0
    )  # invoice numbers are gap-free
    assert (
        scalar("""SELECT count(*) FROM gst_documents a JOIN gst_documents b
        ON a.store_id = b.store_id AND a.financial_year = b.financial_year
        AND split_part(a.number, '/', 3)::int < split_part(b.number, '/', 3)::int
        AND a.issued_at > b.issued_at""")
        == 0
    )  # numbers rise with the clock

    # The seeded accounts work and the reports see the data.
    owner = login(client, "owner@example.com", PASSWORD)
    report = client.get("/reports/sales", headers=owner, params={"group": "month"}).json()
    assert report["totals"]["orders"] > 0
    cashier = login(client, "cashier@example.com", PASSWORD)
    assert client.get("/reports/sales", headers=cashier).status_code == 403

    assert main() == 1  # a business exists now: refuses

    monkeypatch.setattr(get_settings(), "environment", "production")
    assert main() == 1  # and never runs outside development


def test_seed_refuses_outside_development_even_on_an_empty_database(monkeypatch: Any) -> None:
    monkeypatch.setattr(get_settings(), "environment", "staging")
    assert main() == 1
    assert scalar("SELECT count(*) FROM businesses") == 0
