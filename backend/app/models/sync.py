import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.mixins import UUIDPrimaryKey

SYNC_STATUSES = ("received", "applied", "conflict", "failed", "rejected")


class SyncOperation(UUIDPrimaryKey, Base):
    """One offline operation (today: a sale) received from a device, and what became of it.

    - received: stored, not yet decided (a crash between the two leaves it here; it is retried)
    - applied:  became a real sale with a final GST invoice
    - conflict: needs a manager (not enough stock, price changed, ...); nothing was booked
    - failed:   cannot be applied as sent (bad data, no GST rate, ...); needs a fix or a rejection
    - rejected: a manager voided it, with a note
    The same client_operation_id always gives the same answer, so retries are safe.
    """

    __tablename__ = "sync_operations"
    __table_args__ = (
        UniqueConstraint("business_id", "client_operation_id", name="uq_sync_operations_client_op"),
        CheckConstraint(
            "status IN ('received','applied','conflict','failed','rejected')", name="status"
        ),
        Index("ix_sync_operations_store_status", "store_id", "status"),
    )

    business_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("businesses.id"), index=True)
    store_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("stores.id"))
    device_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("devices.id"), index=True)
    client_operation_id: Mapped[uuid.UUID] = mapped_column(Uuid)  # also the sale's idempotency key
    kind: Mapped[str] = mapped_column(String(20), default="sale")
    provisional_number: Mapped[str | None] = mapped_column(String(40))
    # Who the device says made the sale. Deliberately not a foreign key: an operation must be
    # recorded even when this id is unknown, so that it can be held as a failure, not lost.
    cashier_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    sold_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(10), default="received")
    conflicts: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    error_code: Mapped[str | None] = mapped_column(String(40))
    error_message: Mapped[str | None] = mapped_column(Text)
    sale_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("sales.id"))
    received_by: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolution_note: Mapped[str | None] = mapped_column(Text)
