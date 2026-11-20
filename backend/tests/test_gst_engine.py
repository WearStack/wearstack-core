import random
from datetime import date
from decimal import Decimal as D

import pytest
from fastapi.testclient import TestClient

from app.db.session import SessionLocal
from app.services.gst import (
    financial_year,
    round_to_rupee,
    slab_unit_price,
    split_inclusive,
)
from app.services.tax import resolve_tax_rate


# ---- arithmetic (the rates below are arbitrary test inputs, not statements about GST law) ----
@pytest.mark.parametrize(
    ("gross", "rate", "taxable", "cgst", "sgst"),
    [
        ("1299.00", "5", "1237.14", "30.93", "30.93"),
        ("1899.00", "18", "1609.32", "144.84", "144.84"),
        ("105.00", "5", "100.00", "2.50", "2.50"),
        ("100.00", "5", "95.24", "2.38", "2.38"),
        ("1.07", "5", "1.02", "0.03", "0.02"),  # odd paisa goes to SGST
        ("0.00", "12", "0.00", "0.00", "0.00"),
        ("500.00", "0", "500.00", "0.00", "0.00"),  # exempt / nil-rated
    ],
)
def test_intra_state_split(gross: str, rate: str, taxable: str, cgst: str, sgst: str) -> None:
    r = split_inclusive(D(gross), D(rate), interstate=False)
    assert (r.taxable, r.cgst, r.sgst, r.igst) == (D(taxable), D(cgst), D(sgst), D("0.00"))


def test_inter_state_is_all_igst() -> None:
    r = split_inclusive(D("1299.00"), D("5"), interstate=True)
    assert (r.taxable, r.cgst, r.sgst, r.igst) == (D("1237.14"), D("0"), D("0"), D("61.86"))


def test_invariants_hold_for_many_random_amounts() -> None:
    rng = random.Random(42)
    for _ in range(20_000):
        gross = D(rng.randint(0, 5_000_000)) / 100
        rate = rng.choice([D("0"), D("0.25"), D("3"), D("5"), D("12"), D("18"), D("28")])
        for interstate in (False, True):
            r = split_inclusive(gross, rate, interstate)
            assert r.taxable + r.tax == r.gross == gross  # no paisa created or lost
            assert r.taxable >= 0 and r.tax >= 0
            assert r.taxable.as_tuple().exponent == -2  # always 2 decimal places
            if not interstate:
                assert abs(r.cgst - r.sgst) <= D("0.01")
            else:
                assert r.cgst == r.sgst == 0


def test_no_floats_leak_into_results() -> None:
    r = split_inclusive(D("1299.00"), D("5"), False)
    assert all(isinstance(v, D) for v in (r.gross, r.taxable, r.cgst, r.sgst, r.igst, r.rate))


def test_rejects_bad_input() -> None:
    with pytest.raises(ValueError):
        split_inclusive(D("-1"), D("5"), False)
    with pytest.raises(ValueError):
        split_inclusive(D("10"), D("101"), False)


def test_round_to_rupee_is_half_up_with_explicit_round_off() -> None:
    assert round_to_rupee(D("1299.50")) == (D("1300.00"), D("0.50"))
    assert round_to_rupee(D("1299.49")) == (D("1299.00"), D("-0.49"))
    assert round_to_rupee(D("1299.00")) == (D("1299.00"), D("0.00"))
    total, off = round_to_rupee(D("3198.00") + D("0.50"))
    assert total == D("3199.00") and off == D("0.50")


def test_financial_year_boundaries() -> None:
    assert financial_year(date(2026, 3, 31)) == "2025-26"
    assert financial_year(date(2026, 4, 1)) == "2026-27"
    assert financial_year(date(2026, 12, 31)) == "2026-27"
    assert financial_year(date(2099, 6, 1)) == "2099-00"


def test_slab_price_basis() -> None:
    assert slab_unit_price(D("3000"), 2, D("1000"), "after_discount") == D("2500")
    assert slab_unit_price(D("3000"), 2, D("1000"), "before_discount") == D("3000")
    # Not rounded: 2500.00 vs 2499.995 must stay distinguishable at a slab boundary.
    assert slab_unit_price(D("2500.00"), 3, D("0.01"), "after_discount") < D("2500")
    with pytest.raises(ValueError):
        slab_unit_price(D("100"), 1, D("101"), "after_discount")
    with pytest.raises(ValueError):
        slab_unit_price(D("100"), 0, D("0"), "after_discount")


# ---- rate resolution with price slabs and effective dates ----
def _slab(client: TestClient, owner: dict[str, str], **kw: object) -> dict[str, str]:
    body = {"name": "Slabbed", "effective_from": "2020-01-01", **kw}
    res = client.post("/tax-rates", headers=owner, json=body)
    return res  # type: ignore[return-value]


def test_price_slabs_pick_the_right_rate_at_boundaries(
    client: TestClient, owner: dict[str, str]
) -> None:
    low = _slab(client, owner, rate="5", max_unit_price="1000")
    high = _slab(client, owner, rate="12", min_unit_price="1000")
    assert low.status_code == high.status_code == 201  # (.., 1000] and (1000, ..) tile exactly
    base = low.json()["id"]

    def rate_at(price: str, on: date = date(2026, 1, 1)) -> str | None:
        with SessionLocal() as db:
            r = resolve_tax_rate(db, base, on, D(price))  # type: ignore[arg-type]
            return str(r.rate) if r else None

    assert rate_at("0.01") == "5.00"
    assert rate_at("1000") == "5.00"  # "up to 1000" includes 1000
    assert rate_at("1000.01") == "12.00"  # "above 1000" starts just over it
    assert rate_at("999999") == "12.00"
    # Without a price, a slabbed class cannot answer.
    with SessionLocal() as db:
        assert resolve_tax_rate(db, base, date(2026, 1, 1)) is None  # type: ignore[arg-type]


def test_overlapping_slabs_are_rejected_but_adjacent_are_fine(
    client: TestClient, owner: dict[str, str]
) -> None:
    assert _slab(client, owner, rate="5", max_unit_price="1000").status_code == 201
    assert _slab(client, owner, rate="9", min_unit_price="500").status_code == 409
    assert _slab(client, owner, rate="9", max_unit_price="1500").status_code == 409
    assert _slab(client, owner, rate="12", min_unit_price="1000").status_code == 201
    # A slab row that overlaps in both date and price is rejected by the database too.
    assert _slab(client, owner, rate="1", max_unit_price="800").status_code == 409


def test_slab_dates_and_prices_both_apply(client: TestClient, owner: dict[str, str]) -> None:
    old = _slab(client, owner, rate="5", max_unit_price="1000", effective_to="2025-12-31").json()
    new = _slab(client, owner, rate="7", max_unit_price="1000", effective_from="2026-01-01").json()
    assert new["id"]
    with SessionLocal() as db:
        got = resolve_tax_rate(db, old["id"], date(2025, 6, 1), D("500"))
        assert got is not None and str(got.rate) == "5.00"
        got = resolve_tax_rate(db, old["id"], date(2026, 6, 1), D("500"))
        assert got is not None and str(got.rate) == "7.00"
        assert (
            resolve_tax_rate(db, old["id"], date(2026, 6, 1), D("5000")) is None
        )  # no slab covers it


def test_slab_validation(client: TestClient, owner: dict[str, str]) -> None:
    assert (
        _slab(client, owner, rate="5", min_unit_price="500", max_unit_price="500").status_code
        == 422
    )
    assert (
        _slab(client, owner, rate="5", min_unit_price="900", max_unit_price="100").status_code
        == 422
    )
    assert _slab(client, owner, rate="5", min_unit_price="-1").status_code == 422
