import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.gstin import check_char, is_valid_gstin, validate_gstin
from app.db.session import engine
from tests.conftest import SETUP_BODY


def test_known_gstin_is_valid_and_typos_are_caught() -> None:
    assert is_valid_gstin("27AAPFU0939F1ZV")
    assert is_valid_gstin("27aapfu0939f1zv")  # case-insensitive
    # Any single-character slip breaks the check character.
    for bad in ("27AAPFU0939F1ZW", "27AAPFU0939F1ZU", "27AAPFU0938F1ZV", "27AAPFV0939F1ZV"):
        assert not is_valid_gstin(bad), bad
    assert not is_valid_gstin("00AAPFU0939F1ZV")  # no such state code
    assert not is_valid_gstin("27AAPFU0939F1Y" + check_char("27AAPFU0939F1Y"))  # 14th must be Z
    assert not is_valid_gstin("27AAPFU0939F1Z")  # too short
    assert not is_valid_gstin("")


def test_validate_gstin_normalises_and_passes_none() -> None:
    assert validate_gstin(None) is None and validate_gstin("") is None
    assert validate_gstin("27aapfu0939f1zv") == "27AAPFU0939F1ZV"
    with pytest.raises(ValueError):
        validate_gstin("27AAPFU0939F1ZW")


def test_setup_and_store_reject_an_invalid_gstin(client: TestClient) -> None:
    bad = client.post("/setup", json={**SETUP_BODY, "gstin": "27AAPFU0939F1ZW"})
    assert bad.status_code == 422 and "GSTIN" in str(bad.json())
    assert client.post("/setup", json=SETUP_BODY).status_code == 201


def test_store_gstin_is_validated_on_create_and_update(
    client: TestClient, owner: dict[str, str], store_id: str
) -> None:
    base = {"code": "B2", "name": "B2", "state_code": "27"}
    assert (
        client.post("/stores", headers=owner, json={**base, "gstin": "27AAPFU0939F1ZW"}).status_code
        == 422
    )
    ok = client.post("/stores", headers=owner, json={**base, "gstin": "27aapfu0939f1zv"})
    assert ok.status_code == 201 and ok.json()["gstin"] == "27AAPFU0939F1ZV"
    assert (
        client.patch(f"/stores/{store_id}", headers=owner, json={"gstin": "nope"}).status_code
        == 422
    )


@pytest.fixture
def stocked(
    client: TestClient, owner: dict[str, str], store_id: str, make_product: Any
) -> dict[str, Any]:
    rate = client.post(
        "/tax-rates",
        headers=owner,
        json={"name": "R5", "rate": "5", "effective_from": "2020-01-01"},
    ).json()["id"]
    v = make_product(price="100.00", tax_rate_id=rate)["variants"][0]["id"]
    client.post(
        "/inventory/movements",
        headers=owner,
        json={"store_id": store_id, "variant_id": v, "kind": "opening", "quantity": 5},
    )
    return {"variant": v, "store": store_id}


def _sale(stocked: dict[str, Any]) -> dict[str, Any]:
    return {
        "idempotency_key": str(uuid.uuid4()),
        "store_id": stocked["store"],
        "items": [{"variant_id": stocked["variant"], "quantity": 1}],
        "payments": [{"method": "cash", "amount": "100.00"}],
    }


def test_selling_is_blocked_until_the_seller_has_a_gstin(
    client: TestClient, owner: dict[str, str], stocked: dict[str, Any]
) -> None:
    assert client.post("/sales", headers=owner, json=_sale(stocked)).status_code == 201  # has one
    with engine.begin() as conn:  # simulate a business that never entered a GSTIN
        conn.execute(text("UPDATE businesses SET gstin = NULL"))
        conn.execute(text("UPDATE stores SET gstin = NULL"))
    blocked = client.post("/sales", headers=owner, json=_sale(stocked))
    assert blocked.status_code == 409 and "GSTIN" in blocked.json()["detail"]
    assert (
        client.post(
            "/sales/quote",
            headers=owner,
            json={
                "store_id": stocked["store"],
                "items": [{"variant_id": stocked["variant"], "quantity": 1}],
            },
        ).status_code
        == 409
    )
    # Nothing was sold or numbered by the blocked attempts; adding the GSTIN unblocks billing.
    fixed = client.patch(
        f"/stores/{stocked['store']}", headers=owner, json={"gstin": "27AAPFU0939F1ZV"}
    )
    assert fixed.status_code == 200
    ok = client.post("/sales", headers=owner, json=_sale(stocked))
    assert ok.status_code == 201 and ok.json()["invoice_number"].endswith("/00002")
