import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
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
from app.models.mixins import Timestamps, UUIDPrimaryKey

Money = Numeric(12, 2)


class Category(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "categories"
    __table_args__ = (UniqueConstraint("business_id", "name"),)

    business_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("businesses.id"), index=True)
    name: Mapped[str] = mapped_column(String(100))


class Brand(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "brands"
    __table_args__ = (UniqueConstraint("business_id", "name"),)

    business_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("businesses.id"), index=True)
    name: Mapped[str] = mapped_column(String(100))


class TaxRate(UUIDPrimaryKey, Timestamps, Base):
    """Effective-dated GST rate. Rates are configuration, never hardcoded in code."""

    __tablename__ = "tax_rates"
    __table_args__ = (
        # No-overlap is enforced by exclusion constraint ex_tax_rates_no_overlap (migration 0003).
        CheckConstraint("rate >= 0 AND rate <= 100", name="rate_range"),
        CheckConstraint("effective_to IS NULL OR effective_to >= effective_from", name="dates"),
        CheckConstraint(
            "min_unit_price IS NULL OR max_unit_price IS NULL OR max_unit_price > min_unit_price",
            name="price_slab",
        ),
    )

    business_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("businesses.id"), index=True)
    name: Mapped[str] = mapped_column(String(50))
    rate: Mapped[Decimal] = mapped_column(Numeric(5, 2))  # total GST %, e.g. 5.00
    effective_from: Mapped[date] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)
    # Optional per-unit price slab. Applies when min < price <= max (NULL = unbounded), so that
    # "up to X" and "above X" slabs tile without a gap or overlap.
    min_unit_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    max_unit_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))


class Product(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint("selling_price >= 0 AND cost_price >= 0", name="non_negative_prices"),
    )

    business_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("businesses.id"), index=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    description: Mapped[str | None] = mapped_column(Text)
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("categories.id"), index=True
    )
    brand_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("brands.id"), index=True)
    hsn_code: Mapped[str | None] = mapped_column(String(8))
    tax_rate_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("tax_rates.id"))
    selling_price: Mapped[Decimal] = mapped_column(Money)
    cost_price: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class ProductVariant(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "product_variants"
    __table_args__ = (
        UniqueConstraint("business_id", "sku", name="uq_product_variants_sku"),
        UniqueConstraint("business_id", "barcode", name="uq_product_variants_barcode"),
        UniqueConstraint("product_id", "size", "colour", name="uq_product_variants_option"),
        CheckConstraint(
            "COALESCE(selling_price, 0) >= 0 AND COALESCE(cost_price, 0) >= 0",
            name="non_negative_prices",
        ),
    )

    business_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("businesses.id"), index=True)
    product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("products.id", ondelete="CASCADE"), index=True
    )
    sku: Mapped[str] = mapped_column(String(40))
    barcode: Mapped[str] = mapped_column(String(32))
    size: Mapped[str] = mapped_column(String(30), default="")
    colour: Mapped[str] = mapped_column(String(30), default="")
    # NULL means "use the product's price".
    selling_price: Mapped[Decimal | None] = mapped_column(Money)
    cost_price: Mapped[Decimal | None] = mapped_column(Money)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class ProductImage(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "product_images"

    business_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("businesses.id"), index=True)
    product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("products.id", ondelete="CASCADE"), index=True
    )
    file_name: Mapped[str] = mapped_column(String(100))  # stored name, never user-controlled
    content_type: Mapped[str] = mapped_column(String(50))
    position: Mapped[int] = mapped_column(Integer, default=0)
