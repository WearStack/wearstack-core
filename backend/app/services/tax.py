import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import TaxRate


def resolve_tax_rate(
    db: Session, tax_rate_id: uuid.UUID, on: date, unit_price: Decimal | None = None
) -> TaxRate | None:
    """A product points at one rate row, which stands for a named tax class. The rate that
    applies is the row of that class whose date window covers `on` and, if the class has price
    slabs, whose slab contains `unit_price` (min < price <= max). A GST change is a new row, so
    old invoices keep the rate they were issued under."""
    base = db.get(TaxRate, tax_rate_id)
    if base is None:
        return None
    stmt = select(TaxRate).where(
        TaxRate.business_id == base.business_id,
        TaxRate.name == base.name,
        TaxRate.effective_from <= on,
        (TaxRate.effective_to.is_(None)) | (TaxRate.effective_to >= on),
    )
    if unit_price is None:
        # No price given: only a class without slabs can answer.
        stmt = stmt.where(TaxRate.min_unit_price.is_(None), TaxRate.max_unit_price.is_(None))
    else:
        stmt = stmt.where(
            (TaxRate.min_unit_price.is_(None)) | (TaxRate.min_unit_price < unit_price),
            (TaxRate.max_unit_price.is_(None)) | (TaxRate.max_unit_price >= unit_price),
        )
    return db.scalars(stmt.order_by(TaxRate.effective_from.desc())).first()
