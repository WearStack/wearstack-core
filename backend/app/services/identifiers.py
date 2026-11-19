import re
import secrets
import uuid

import barcode
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ProductVariant

_SKU_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _abbr(value: str, n: int) -> str:
    return re.sub(r"[^A-Z0-9]", "", value.upper())[:n]


def generate_sku(db: Session, business_id: uuid.UUID, name: str, size: str, colour: str) -> str:
    parts = [_abbr(name, 3) or "ITM", _abbr(size, 3), _abbr(colour, 3)]
    prefix = "-".join(p for p in parts if p)
    for _ in range(20):
        sku = f"{prefix}-{''.join(secrets.choice(_SKU_ALPHABET) for _ in range(4))}"
        if not db.scalar(
            select(ProductVariant.id).where(
                ProductVariant.business_id == business_id, ProductVariant.sku == sku
            )
        ):
            return sku
    raise RuntimeError("Could not generate a unique SKU")


def generate_barcode(db: Session, business_id: uuid.UUID) -> str:
    """Internal-use EAN-13: prefix '2' is reserved for in-store use, so it never clashes with
    manufacturer barcodes."""
    for _ in range(20):
        body = "2" + "".join(secrets.choice("0123456789") for _ in range(11))
        code: str = barcode.get("ean13", body).get_fullcode()
        if not db.scalar(
            select(ProductVariant.id).where(
                ProductVariant.business_id == business_id, ProductVariant.barcode == code
            )
        ):
            return code
    raise RuntimeError("Could not generate a unique barcode")


def barcode_svg(code: str) -> bytes:
    from barcode.writer import SVGWriter

    kind = "ean13" if re.fullmatch(r"\d{13}", code) else "code128"
    svg: bytes = barcode.get(
        kind, code[:12] if kind == "ean13" else code, writer=SVGWriter()
    ).render()
    return svg
