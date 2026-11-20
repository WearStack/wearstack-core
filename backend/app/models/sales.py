import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.catalog import Money
from app.models.mixins import UUIDPrimaryKey

Total = Numeric(14, 2)


class Sale(UUIDPrimaryKey, Base):
    """A completed sale. Immutable once written (enforced by a database trigger)."""

    __tablename__ = "sales"
    __table_args__ = (
        UniqueConstraint("business_id", "idempotency_key", name="uq_sales_idempotency_key"),
        CheckConstraint("grand_total >= 0", name="non_negative_total"),
    )

    business_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("businesses.id"), index=True)
    store_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("stores.id"), index=True)
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("customers.id"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"))
    idempotency_key: Mapped[uuid.UUID] = mapped_column(Uuid)
    sold_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    place_of_supply: Mapped[str] = mapped_column(String(2))
    is_interstate: Mapped[bool] = mapped_column()
    discount_total: Mapped[Decimal] = mapped_column(Total)
    taxable_total: Mapped[Decimal] = mapped_column(Total)
    cgst_total: Mapped[Decimal] = mapped_column(Total)
    sgst_total: Mapped[Decimal] = mapped_column(Total)
    igst_total: Mapped[Decimal] = mapped_column(Total)
    round_off: Mapped[Decimal] = mapped_column(Total)
    grand_total: Mapped[Decimal] = mapped_column(Total)


class SaleItem(UUIDPrimaryKey, Base):
    """Line snapshot: later product, price or tax edits never change a past sale."""

    __tablename__ = "sale_items"
    __table_args__ = (CheckConstraint("quantity > 0", name="positive_quantity"),)

    sale_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("sales.id"), index=True)
    variant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("product_variants.id"), index=True
    )
    product_name: Mapped[str] = mapped_column(String(200))
    variant_label: Mapped[str] = mapped_column(String(80))
    sku: Mapped[str] = mapped_column(String(40))
    hsn_code: Mapped[str | None] = mapped_column(String(8))
    line_no: Mapped[int] = mapped_column(Integer)  # position on the bill, in the order entered
    quantity: Mapped[int] = mapped_column(Integer)
    unit_price: Mapped[Decimal] = mapped_column(Money)  # tax-inclusive, before discount
    discount: Mapped[Decimal] = mapped_column(Money)  # total for the line
    unit_cost: Mapped[Decimal] = mapped_column(Money)  # for margin reporting
    tax_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    tax_rate_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("tax_rates.id"))
    taxable_value: Mapped[Decimal] = mapped_column(Total)
    cgst: Mapped[Decimal] = mapped_column(Total)
    sgst: Mapped[Decimal] = mapped_column(Total)
    igst: Mapped[Decimal] = mapped_column(Total)
    line_total: Mapped[Decimal] = mapped_column(Total)  # tax-inclusive, after discount


class Payment(UUIDPrimaryKey, Base):
    __tablename__ = "payments"
    __table_args__ = (
        CheckConstraint("amount > 0", name="positive_amount"),
        CheckConstraint("method IN ('cash','upi','card')", name="method"),
        CheckConstraint("status IN ('pending','confirmed','failed')", name="status"),
    )

    business_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("businesses.id"), index=True)
    sale_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("sales.id"), index=True)
    method: Mapped[str] = mapped_column(String(10))
    amount: Mapped[Decimal] = mapped_column(Money)
    status: Mapped[str] = mapped_column(String(10))
    reference: Mapped[str | None] = mapped_column(String(100))  # UPI txn id / card approval code
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class InvoiceSequence(UUIDPrimaryKey, Base):
    """Gap-free counter per store, document type and financial year."""

    __tablename__ = "invoice_sequences"
    __table_args__ = (
        UniqueConstraint(
            "business_id", "store_id", "doc_type", "financial_year", name="uq_invoice_seq"
        ),
    )

    business_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("businesses.id"))
    store_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("stores.id"))
    doc_type: Mapped[str] = mapped_column(String(20))
    financial_year: Mapped[str] = mapped_column(String(7))  # e.g. 2026-27
    last_number: Mapped[int] = mapped_column(Integer, default=0)


class GstDocument(UUIDPrimaryKey, Base):
    """The legal document for a sale (tax invoice now; credit notes in a later phase)."""

    __tablename__ = "gst_documents"
    __table_args__ = (
        UniqueConstraint("business_id", "doc_type", "number", name="uq_gst_documents_number"),
        UniqueConstraint("sale_id", "doc_type", name="uq_gst_documents_sale"),
    )

    business_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("businesses.id"), index=True)
    store_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("stores.id"), index=True)
    sale_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("sales.id"))
    doc_type: Mapped[str] = mapped_column(String(20))
    number: Mapped[str] = mapped_column(String(16))  # GST caps invoice numbers at 16 characters
    financial_year: Mapped[str] = mapped_column(String(7))
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    seller: Mapped[dict[str, Any]] = mapped_column(JSONB)  # snapshot of business and store
    buyer: Mapped[dict[str, Any]] = mapped_column(JSONB)  # snapshot of customer (or walk-in)
