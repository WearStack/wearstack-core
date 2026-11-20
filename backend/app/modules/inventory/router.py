import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, require_permission
from app.db.session import get_db
from app.models import Inventory, Product, ProductVariant, StockMovement
from app.services.audit import record_audit
from app.services.inventory import InsufficientStock, apply_movement

router = APIRouter(prefix="/inventory", tags=["inventory"])


class StockRow(BaseModel):
    variant_id: uuid.UUID
    product_id: uuid.UUID
    product_name: str
    sku: str
    barcode: str
    size: str
    colour: str
    quantity: int
    reorder_level: int
    low_stock: bool


class MovementIn(BaseModel):
    store_id: uuid.UUID
    variant_id: uuid.UUID
    kind: Literal["opening", "adjustment"]
    # opening: must be positive. adjustment: signed (negative removes stock).
    quantity: int = Field(ge=-100_000, le=100_000)
    reason: str | None = Field(default=None, max_length=500)


class MovementOut(BaseModel):
    id: uuid.UUID
    variant_id: uuid.UUID
    store_id: uuid.UUID
    movement_type: str
    quantity_delta: int
    balance_after: int
    reason: str | None
    user_id: uuid.UUID | None
    created_at: datetime

    model_config = {"from_attributes": True}


class ReorderIn(BaseModel):
    store_id: uuid.UUID
    variant_id: uuid.UUID
    reorder_level: int = Field(ge=0, le=100_000)


def _variant(db: Session, ctx: AuthContext, variant_id: uuid.UUID) -> ProductVariant:
    variant = db.get(ProductVariant, variant_id)
    if variant is None or variant.business_id != ctx.business_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Variant not found")
    return variant


@router.get("", response_model=list[StockRow])
def list_stock(
    store_id: uuid.UUID,
    q: str | None = None,
    low_stock: bool = False,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    ctx: AuthContext = Depends(require_permission("inventory:read")),
    db: Session = Depends(get_db),
) -> list[StockRow]:
    """Every active variant with its balance in the store (0 if it has never been stocked)."""
    ctx.require_store(store_id)
    qty = func.coalesce(Inventory.quantity, 0)
    reorder = func.coalesce(Inventory.reorder_level, 0)
    stmt = (
        select(ProductVariant, Product.name, qty, reorder)
        .join(Product, Product.id == ProductVariant.product_id)
        .outerjoin(
            Inventory,
            (Inventory.variant_id == ProductVariant.id) & (Inventory.store_id == store_id),
        )
        .where(
            ProductVariant.business_id == ctx.business_id,
            ProductVariant.is_active.is_(True),
            Product.is_active.is_(True),
        )
    )
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            or_(
                Product.name.ilike(like),
                ProductVariant.sku.ilike(like),
                ProductVariant.barcode == q,
            )
        )
    if low_stock:  # "low" means a reorder level is set and stock has reached it
        stmt = stmt.where(reorder > 0, qty <= reorder)
    rows = db.execute(
        stmt.order_by(Product.name, ProductVariant.size, ProductVariant.colour)
        .limit(limit)
        .offset(offset)
    ).all()
    return [
        StockRow(
            variant_id=v.id,
            product_id=v.product_id,
            product_name=name,
            sku=v.sku,
            barcode=v.barcode,
            size=v.size,
            colour=v.colour,
            quantity=quantity,
            reorder_level=level,
            low_stock=level > 0 and quantity <= level,
        )
        for v, name, quantity, level in rows
    ]


@router.post("/movements", response_model=MovementOut, status_code=status.HTTP_201_CREATED)
def create_movement(
    body: MovementIn,
    ctx: AuthContext = Depends(require_permission("inventory:adjust")),
    db: Session = Depends(get_db),
) -> StockMovement:
    ctx.require_store(body.store_id)
    _variant(db, ctx, body.variant_id)
    if body.kind == "opening":
        if body.quantity <= 0:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Opening stock must be > 0")
        has_history = db.scalar(
            select(func.count())
            .select_from(StockMovement)
            .where(
                StockMovement.variant_id == body.variant_id,
                StockMovement.store_id == body.store_id,
            )
        )
        if has_history:
            raise HTTPException(
                status.HTTP_409_CONFLICT, "Opening stock already set; use an adjustment"
            )
    elif body.quantity == 0 or not (body.reason and body.reason.strip()):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "An adjustment needs a non-zero change and a reason",
        )
    try:
        movement = apply_movement(
            db,
            business_id=ctx.business_id,
            store_id=body.store_id,
            variant_id=body.variant_id,
            movement_type=body.kind,
            delta=body.quantity,
            user_id=ctx.user.id,
            reason=body.reason,
        )
    except InsufficientStock as e:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from None
    record_audit(
        db,
        business_id=ctx.business_id,
        user_id=ctx.user.id,
        action=f"stock.{body.kind}",
        entity_type="variant",
        entity_id=body.variant_id,
        after={"delta": body.quantity, "balance": movement.balance_after, "reason": body.reason},
    )
    db.commit()
    return movement


@router.get("/movements", response_model=list[MovementOut])
def list_movements(
    store_id: uuid.UUID,
    variant_id: uuid.UUID | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    ctx: AuthContext = Depends(require_permission("inventory:read")),
    db: Session = Depends(get_db),
) -> list[StockMovement]:
    ctx.require_store(store_id)
    stmt = select(StockMovement).where(
        StockMovement.business_id == ctx.business_id, StockMovement.store_id == store_id
    )
    if variant_id:
        stmt = stmt.where(StockMovement.variant_id == variant_id)
    stmt = (
        stmt.order_by(StockMovement.created_at.desc(), StockMovement.id).limit(limit).offset(offset)
    )
    return list(db.scalars(stmt))


@router.put("/reorder-level", status_code=status.HTTP_204_NO_CONTENT)
def set_reorder_level(
    body: ReorderIn,
    ctx: AuthContext = Depends(require_permission("inventory:adjust")),
    db: Session = Depends(get_db),
) -> None:
    ctx.require_store(body.store_id)
    _variant(db, ctx, body.variant_id)
    stmt = insert(Inventory).values(
        variant_id=body.variant_id,
        store_id=body.store_id,
        business_id=ctx.business_id,
        quantity=0,
        reorder_level=body.reorder_level,
    )
    db.execute(
        stmt.on_conflict_do_update(
            index_elements=["variant_id", "store_id"], set_={"reorder_level": body.reorder_level}
        )
    )
    db.commit()
