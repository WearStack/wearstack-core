import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.catalog import Money
from app.models.mixins import Timestamps, UUIDPrimaryKey


class Purchase(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "purchases"
    __table_args__ = (UniqueConstraint("business_id", "supplier_id", "bill_number"),)

    business_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("businesses.id"), index=True)
    store_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("stores.id"), index=True)
    supplier_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("suppliers.id"), index=True)
    bill_number: Mapped[str] = mapped_column(String(50))
    bill_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft | received
    total: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    notes: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))
    received_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PurchaseItem(UUIDPrimaryKey, Base):
    __tablename__ = "purchase_items"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="positive_quantity"),
        CheckConstraint("unit_cost >= 0", name="non_negative_cost"),
        UniqueConstraint("purchase_id", "variant_id"),
    )

    purchase_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("purchases.id", ondelete="CASCADE"), index=True
    )
    variant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("product_variants.id"))
    quantity: Mapped[int] = mapped_column(Integer)
    unit_cost: Mapped[Decimal] = mapped_column(Money)  # per unit, before tax
    line_total: Mapped[Decimal] = mapped_column(Numeric(14, 2))
