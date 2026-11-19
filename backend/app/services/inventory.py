import uuid

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import Inventory, StockMovement


class InsufficientStock(Exception):
    def __init__(self, available: int, requested: int) -> None:
        super().__init__(f"Only {available} in stock, cannot remove {requested}")
        self.available = available
        self.requested = requested


def apply_movement(
    db: Session,
    *,
    business_id: uuid.UUID,
    store_id: uuid.UUID,
    variant_id: uuid.UUID,
    movement_type: str,
    delta: int,
    user_id: uuid.UUID | None,
    reason: str | None = None,
    reference_type: str | None = None,
    reference_id: uuid.UUID | None = None,
) -> StockMovement:
    """The only way stock changes. Locks the balance row, appends to the ledger and updates the
    balance in the caller's transaction. Raises InsufficientStock rather than going negative."""
    if delta == 0:
        raise ValueError("A stock movement must change the quantity")
    db.execute(
        insert(Inventory)
        .values(variant_id=variant_id, store_id=store_id, business_id=business_id, quantity=0)
        .on_conflict_do_nothing(index_elements=["variant_id", "store_id"])
    )
    row = db.execute(
        select(Inventory)
        .where(Inventory.variant_id == variant_id, Inventory.store_id == store_id)
        .with_for_update()
    ).scalar_one()
    new_balance = row.quantity + delta
    if new_balance < 0:
        raise InsufficientStock(available=row.quantity, requested=-delta)
    row.quantity = new_balance
    movement = StockMovement(
        business_id=business_id,
        store_id=store_id,
        variant_id=variant_id,
        movement_type=movement_type,
        quantity_delta=delta,
        balance_after=new_balance,
        reason=reason,
        reference_type=reference_type,
        reference_id=reference_id,
        user_id=user_id,
    )
    db.add(movement)
    db.flush()
    return movement
