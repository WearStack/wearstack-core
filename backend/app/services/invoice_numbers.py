import re
import uuid

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import InvoiceSequence

MAX_LENGTH = 16  # GST rule: an invoice number may be at most 16 characters


def format_number(store_code: str, financial_year: str, n: int) -> str:
    prefix = re.sub(r"[^A-Z0-9]", "", store_code.upper())[:4] or "INV"
    number = f"{prefix}/{financial_year[2:4]}-{financial_year[5:7]}/{n:05d}"
    if len(number) > MAX_LENGTH:
        raise ValueError(f"Invoice number {number!r} exceeds {MAX_LENGTH} characters")
    return number


def next_number(
    db: Session,
    *,
    business_id: uuid.UUID,
    store_id: uuid.UUID,
    store_code: str,
    doc_type: str,
    financial_year: str,
) -> str:
    """Gap-free: the counter row is locked and incremented inside the caller's transaction, so a
    rolled-back sale gives its number back, and concurrent sales queue behind the lock."""
    db.execute(
        insert(InvoiceSequence)
        .values(
            business_id=business_id,
            store_id=store_id,
            doc_type=doc_type,
            financial_year=financial_year,
            last_number=0,
        )
        .on_conflict_do_nothing(constraint="uq_invoice_seq")
    )
    seq = db.execute(
        select(InvoiceSequence)
        .where(
            InvoiceSequence.business_id == business_id,
            InvoiceSequence.store_id == store_id,
            InvoiceSequence.doc_type == doc_type,
            InvoiceSequence.financial_year == financial_year,
        )
        .with_for_update()
    ).scalar_one()
    seq.last_number += 1
    return format_number(store_code, financial_year, seq.last_number)
