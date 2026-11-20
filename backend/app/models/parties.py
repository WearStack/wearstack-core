import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.mixins import Timestamps, UUIDPrimaryKey


class Supplier(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "suppliers"
    __table_args__ = (UniqueConstraint("business_id", "name"),)

    business_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("businesses.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    gstin: Mapped[str | None] = mapped_column(String(15))
    phone: Mapped[str | None] = mapped_column(String(20))
    email: Mapped[str | None] = mapped_column(String(254))
    address: Mapped[str | None] = mapped_column(String(500))
    state_code: Mapped[str | None] = mapped_column(String(2))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Customer(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "customers"
    __table_args__ = (UniqueConstraint("business_id", "phone"),)  # NULL phones never collide

    business_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("businesses.id"), index=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    phone: Mapped[str | None] = mapped_column(String(20))
    email: Mapped[str | None] = mapped_column(String(254))
    gstin: Mapped[str | None] = mapped_column(String(15))  # present => B2B invoice
    state_code: Mapped[str | None] = mapped_column(String(2))
    marketing_consent: Mapped[bool] = mapped_column(Boolean, default=False)
    consent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
