import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.mixins import Timestamps, UUIDPrimaryKey


class Business(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "businesses"

    name: Mapped[str] = mapped_column(String(200))
    legal_name: Mapped[str | None] = mapped_column(String(200))
    gstin: Mapped[str | None] = mapped_column(String(15))
    state_code: Mapped[str] = mapped_column(String(2))  # GST state code, drives place-of-supply


class Store(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "stores"
    __table_args__ = (UniqueConstraint("business_id", "code"),)

    business_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("businesses.id"), index=True)
    code: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(200))
    address: Mapped[str | None] = mapped_column(String(500))
    state_code: Mapped[str] = mapped_column(String(2))
    gstin: Mapped[str | None] = mapped_column(String(15))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Device(UUIDPrimaryKey, Timestamps, Base):
    """A registered POS client. Populated from Phase 5 (offline sync)."""

    __tablename__ = "devices"
    __table_args__ = (UniqueConstraint("business_id", "identifier"),)

    business_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("businesses.id"), index=True)
    store_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("stores.id"), index=True)
    identifier: Mapped[str] = mapped_column(String(100))
    name: Mapped[str] = mapped_column(String(100))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
