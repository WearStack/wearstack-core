import io
from datetime import date
from typing import Any

from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import Business, Product, ProductVariant
from app.services.rbac import create_default_roles
from app.services.tax import resolve_tax_rate


def test_create_product_generates_sku_and_ean13_barcodes(
    client: TestClient, owner: dict[str, str], make_product: Any
) -> None:
    product = make_product()
    assert len(product["variants"]) == 2
    skus = {v["sku"] for v in product["variants"]}
    barcodes = {v["barcode"] for v in product["variants"]}
    assert len(skus) == len(barcodes) == 2
    for code in barcodes:
        assert len(code) == 13 and code.isdigit() and code.startswith("2")
    assert all(s.startswith("CLA-") for s in skus)


def test_ean13_check_digit_is_valid(make_product: Any) -> None:
    code = make_product()["variants"][0]["barcode"]
    digits = [int(c) for c in code]
    total = sum(d * (3 if i % 2 else 1) for i, d in enumerate(digits[:12]))
    assert (10 - total % 10) % 10 == digits[12]


def test_variant_price_falls_back_to_product_and_can_be_overridden(
    client: TestClient, owner: dict[str, str]
) -> None:
    res = client.post(
        "/products",
        headers=owner,
        json={
            "name": "Denim",
            "selling_price": "1899.00",
            "cost_price": "900.00",
            "variants": [{"size": "30"}, {"size": "32", "selling_price": "1999.00"}],
        },
    )
    by_size = {v["size"]: v for v in res.json()["variants"]}
    assert by_size["30"]["selling_price"] == "1899.00" and not by_size["30"]["has_price_override"]
    assert by_size["32"]["selling_price"] == "1999.00" and by_size["32"]["has_price_override"]
    assert by_size["30"]["cost_price"] == "900.00"


def test_money_is_exact_decimal_not_float(client: TestClient, owner: dict[str, str]) -> None:
    res = client.post("/products", headers=owner, json={"name": "X", "selling_price": "0.10"})
    assert res.json()["selling_price"] == "0.10"
    too_precise = client.post(
        "/products", headers=owner, json={"name": "Y", "selling_price": "1.005"}
    )
    assert too_precise.status_code == 422


def test_validation_rejects_bad_input(client: TestClient, owner: dict[str, str]) -> None:
    base = {"name": "Bad", "selling_price": "10.00"}
    assert (
        client.post("/products", headers=owner, json={**base, "selling_price": "-1"}).status_code
        == 422
    )
    assert (
        client.post("/products", headers=owner, json={**base, "hsn_code": "12AB"}).status_code
        == 422
    )
    assert client.post("/products", headers=owner, json={**base, "name": ""}).status_code == 422


def test_duplicate_sku_conflicts_and_leaves_no_partial_product(
    client: TestClient, owner: dict[str, str], make_product: Any
) -> None:
    existing = make_product()["variants"][0]["sku"]
    res = client.post(
        "/products",
        headers=owner,
        json={
            "name": "Other",
            "selling_price": "100.00",
            "variants": [{"size": "S", "sku": existing}],
        },
    )
    assert res.status_code == 409
    names = {p["name"] for p in client.get("/products", headers=owner).json()}
    assert "Other" not in names


def test_duplicate_size_colour_in_one_product_conflicts(
    client: TestClient, owner: dict[str, str]
) -> None:
    res = client.post(
        "/products",
        headers=owner,
        json={
            "name": "Dup",
            "selling_price": "100.00",
            "variants": [{"size": "M", "colour": "Red"}, {"size": "M", "colour": "Red"}],
        },
    )
    assert res.status_code == 409


def test_add_variant_later_and_update_it(
    client: TestClient, owner: dict[str, str], make_product: Any
) -> None:
    product = make_product()
    res = client.post(
        f"/products/{product['id']}/variants", headers=owner, json={"size": "XL", "colour": "Blue"}
    )
    assert res.status_code == 201
    vid = res.json()["id"]
    upd = client.patch(f"/variants/{vid}", headers=owner, json={"selling_price": "1500.00"})
    assert upd.json()["selling_price"] == "1500.00" and upd.json()["has_price_override"]
    assert (
        client.patch(
            f"/variants/{vid}", headers=owner, json={"sku": product["variants"][0]["sku"]}
        ).status_code
        == 409
    )


def test_search_and_barcode_lookup(
    client: TestClient, owner: dict[str, str], make_product: Any
) -> None:
    product = make_product("Linen Casual Shirt")
    make_product("Slim Denim")
    assert [
        p["name"] for p in client.get("/products", headers=owner, params={"q": "linen"}).json()
    ] == ["Linen Casual Shirt"]
    v = product["variants"][0]
    exact = client.get("/variants/lookup", headers=owner, params={"q": v["barcode"]}).json()
    assert [r["variant_id"] for r in exact] == [v["id"]]
    by_name = client.get("/variants/lookup", headers=owner, params={"q": "denim"}).json()
    assert by_name and all("Denim" in r["product_name"] for r in by_name)
    by_sku = client.get("/variants/lookup", headers=owner, params={"q": v["sku"].lower()}).json()
    assert [r["variant_id"] for r in by_sku] == [v["id"]]


def test_inactive_products_are_hidden_from_lists_and_lookup(
    client: TestClient, owner: dict[str, str], make_product: Any
) -> None:
    p = make_product("Retired Tee")
    client.patch(f"/products/{p['id']}", headers=owner, json={"is_active": False})
    assert client.get("/products", headers=owner).json() == []
    assert (
        len(client.get("/products", headers=owner, params={"include_inactive": True}).json()) == 1
    )
    assert client.get("/variants/lookup", headers=owner, params={"q": "Retired"}).json() == []


def test_barcode_image_is_svg(client: TestClient, owner: dict[str, str], make_product: Any) -> None:
    vid = make_product()["variants"][0]["id"]
    res = client.get(f"/variants/{vid}/barcode.svg", headers=owner)
    assert res.status_code == 200 and res.headers["content-type"] == "image/svg+xml"
    assert b"<svg" in res.content


def test_cashier_can_read_but_not_write_catalogue(
    client: TestClient, make_user: Any, make_product: Any
) -> None:
    product = make_product()
    cashier = make_user("Cashier", "cash@example.com")
    assert client.get("/products", headers=cashier).status_code == 200
    assert client.get("/variants/lookup", headers=cashier, params={"q": "shirt"}).status_code == 200
    assert (
        client.post(
            "/products", headers=cashier, json={"name": "x", "selling_price": "1"}
        ).status_code
        == 403
    )
    assert (
        client.patch(f"/products/{product['id']}", headers=cashier, json={"name": "y"}).status_code
        == 403
    )


def test_categories_and_brands(client: TestClient, owner: dict[str, str]) -> None:
    cat = client.post("/categories", headers=owner, json={"name": "Shirts"})
    brand = client.post("/brands", headers=owner, json={"name": "Acme"})
    assert cat.status_code == brand.status_code == 201
    assert client.post("/categories", headers=owner, json={"name": "Shirts"}).status_code == 409
    res = client.post(
        "/products",
        headers=owner,
        json={
            "name": "Tagged",
            "selling_price": "10.00",
            "category_id": cat.json()["id"],
            "brand_id": brand.json()["id"],
        },
    )
    assert res.status_code == 201
    listed = client.get("/products", headers=owner, params={"category_id": cat.json()["id"]}).json()
    assert [p["name"] for p in listed] == ["Tagged"]


def test_catalogue_is_isolated_between_businesses(
    client: TestClient, owner: dict[str, str], make_product: Any
) -> None:
    with SessionLocal() as db:
        biz = Business(name="Other", state_code="29")
        db.add(biz)
        db.flush()
        create_default_roles(db, biz.id)
        prod = Product(business_id=biz.id, name="Secret Item", selling_price=1)
        db.add(prod)
        db.flush()
        db.add(
            ProductVariant(
                business_id=biz.id, product_id=prod.id, sku="SECRET", barcode="2000000000017"
            )
        )
        db.commit()
        other_product, other_variant = (
            str(prod.id),
            str(db.scalars(select(ProductVariant.id)).first()),
        )
    assert client.get("/products", headers=owner).json() == []
    assert client.get(f"/products/{other_product}", headers=owner).status_code == 404
    assert (
        client.patch(f"/products/{other_product}", headers=owner, json={"name": "x"}).status_code
        == 404
    )
    assert client.get("/variants/lookup", headers=owner, params={"q": "SECRET"}).json() == []
    assert client.get(f"/variants/{other_variant}/barcode.svg", headers=owner).status_code == 404
    # A product may not reference another business's category.
    with SessionLocal() as db:
        from app.models import Category

        cat = Category(
            business_id=db.scalars(select(Business.id).where(Business.name == "Other")).one(),
            name="C",
        )
        db.add(cat)
        db.commit()
        cat_id = str(cat.id)
    res = client.post(
        "/products", headers=owner, json={"name": "P", "selling_price": "1", "category_id": cat_id}
    )
    assert res.status_code == 422


def test_tax_rates_effective_dating_and_overlap(client: TestClient, owner: dict[str, str]) -> None:
    old = client.post(
        "/tax-rates",
        headers=owner,
        json={
            "name": "Apparel",
            "rate": "5.00",
            "effective_from": "2020-01-01",
            "effective_to": "2025-12-31",
        },
    )
    assert old.status_code == 201
    overlap = client.post(
        "/tax-rates",
        headers=owner,
        json={"name": "Apparel", "rate": "12.00", "effective_from": "2025-06-01"},
    )
    assert overlap.status_code == 409
    new = client.post(
        "/tax-rates",
        headers=owner,
        json={"name": "Apparel", "rate": "12.00", "effective_from": "2026-01-01"},
    )
    assert new.status_code == 201
    # Same dates under a different name do not conflict.
    assert (
        client.post(
            "/tax-rates",
            headers=owner,
            json={"name": "Footwear", "rate": "18.00", "effective_from": "2020-01-01"},
        ).status_code
        == 201
    )

    in_2024 = {
        r["name"]: r["rate"]
        for r in client.get("/tax-rates", headers=owner, params={"on": "2024-06-01"}).json()
    }
    in_2026 = {
        r["name"]: r["rate"]
        for r in client.get("/tax-rates", headers=owner, params={"on": "2026-06-01"}).json()
    }
    assert in_2024 == {"Apparel": "5.00", "Footwear": "18.00"}
    assert in_2026 == {"Apparel": "12.00", "Footwear": "18.00"}

    with SessionLocal() as db:
        resolved = resolve_tax_rate(db, old.json()["id"], date(2026, 6, 1))
        assert resolved is not None and str(resolved.rate) == "12.00"
        assert str(resolve_tax_rate(db, new.json()["id"], date(2024, 6, 1)).rate) == "5.00"  # type: ignore[union-attr]
        assert resolve_tax_rate(db, old.json()["id"], date(2019, 1, 1)) is None


def test_tax_rate_validation_and_ending(client: TestClient, owner: dict[str, str]) -> None:
    assert (
        client.post(
            "/tax-rates",
            headers=owner,
            json={"name": "A", "rate": "150", "effective_from": "2020-01-01"},
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/tax-rates",
            headers=owner,
            json={
                "name": "A",
                "rate": "5",
                "effective_from": "2020-01-01",
                "effective_to": "2019-01-01",
            },
        ).status_code
        == 422
    )
    rate = client.post(
        "/tax-rates", headers=owner, json={"name": "A", "rate": "5", "effective_from": "2020-01-01"}
    ).json()
    ended = client.patch(
        f"/tax-rates/{rate['id']}/end", headers=owner, params={"effective_to": "2025-12-31"}
    )
    assert ended.json()["effective_to"] == "2025-12-31"
    assert (
        client.post(
            "/tax-rates",
            headers=owner,
            json={"name": "A", "rate": "12", "effective_from": "2026-01-01"},
        ).status_code
        == 201
    )


def _png(size: tuple[int, int] = (20, 20)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, "orange").save(buf, "PNG")
    return buf.getvalue()


def test_image_upload_serve_and_delete(
    client: TestClient, owner: dict[str, str], make_product: Any
) -> None:
    pid = make_product()["id"]
    res = client.post(
        f"/products/{pid}/images", headers=owner, files={"file": ("shirt.png", _png(), "image/png")}
    )
    assert res.status_code == 201, res.text
    image = res.json()
    assert image["url"].startswith("/media/") and image["url"].endswith(".png")
    assert "shirt" not in image["url"]  # stored under a generated name
    assert client.get(image["url"]).content == _png()
    assert client.get(f"/products/{pid}", headers=owner).json()["images"][0]["id"] == image["id"]
    assert client.delete(f"/products/{pid}/images/{image['id']}", headers=owner).status_code == 204
    assert client.get(image["url"]).status_code == 404


def test_image_upload_rejects_non_images_and_oversize(
    client: TestClient, owner: dict[str, str], make_product: Any, monkeypatch: Any
) -> None:
    pid = make_product()["id"]
    fake = client.post(
        f"/products/{pid}/images",
        headers=owner,
        files={"file": ("evil.png", b"<script>alert(1)</script>", "image/png")},
    )
    assert fake.status_code == 422
    gif = io.BytesIO()
    Image.new("RGB", (5, 5)).save(gif, "GIF")
    assert (
        client.post(
            f"/products/{pid}/images",
            headers=owner,
            files={"file": ("a.gif", gif.getvalue(), "image/gif")},
        ).status_code
        == 422
    )
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "max_image_bytes", 100)
    big = client.post(
        f"/products/{pid}/images",
        headers=owner,
        files={"file": ("a.png", _png((200, 200)), "image/png")},
    )
    assert big.status_code == 413


def test_cashier_cannot_upload_images(
    client: TestClient, make_user: Any, make_product: Any
) -> None:
    pid = make_product()["id"]
    cashier = make_user("Cashier", "cash@example.com")
    res = client.post(
        f"/products/{pid}/images", headers=cashier, files={"file": ("a.png", _png(), "image/png")}
    )
    assert res.status_code == 403
