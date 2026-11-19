import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import TaxRate


def resolve_tax_rate(db: Session, tax_rate_id: uuid.UUID, on: date) -> TaxRate | None:
    """A product points at one rate row, which stands for a named tax class. The rate that
    applies on a given date is the row of that class whose effective window covers the date,
    so a GST change is a new row, and old invoices keep the rate they were issued under."""
    base = db.get(TaxRate, tax_rate_id)
    if base is None:
        return None
    stmt = (
        select(TaxRate)
        .where(
            TaxRate.business_id == base.business_id,
            TaxRate.name == base.name,
            TaxRate.effective_from <= on,
            (TaxRate.effective_to.is_(None)) | (TaxRate.effective_to >= on),
        )
        .order_by(TaxRate.effective_from.desc())
    )
    return db.scalars(stmt).first()
