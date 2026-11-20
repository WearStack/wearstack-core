import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, require_permission
from app.db.session import get_db
from app.models import Product, ProductVariant, Purchase, PurchaseItem, Supplier
from app.services import gst
from app.services.audit import record_audit
from app.services.inventory import apply_movement

router = APIRouter(tags=["purchasing"])
Cost = Annotated[Decimal, Field(ge=0, max_digits=10, decimal_places=2)]
GSTIN = Annotated[str, Field(pattern=r"^\d{2}[A-Z0-9]{13}$")]


# ---- suppliers ----
class SupplierIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    gstin: GSTIN | None = None
    phone: str | None = Field(default=None, pattern=r"^\+?\d{7,15}$")
    email: EmailStr | None = None
    address: str | None = Field(default=None, max_length=500)
    state_code: str | None = Field(default=None, pattern=r"^\d{2}$")


class SupplierUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    gstin: GSTIN | None = None
    phone: str | None = Field(default=None, pattern=r"^\+?\d{7,15}$")
    email: EmailStr | None = None
    address: str | None = Field(default=None, max_length=500)
    state_code: str | None = Field(default=None, pattern=r"^\d{2}$")
    is_active: bool | None = None


class SupplierOut(SupplierIn):
    id: uuid.UUID
    is_active: bool
    model_config = {"from_attributes": True}


@router.get("/suppliers", response_model=list[SupplierOut])
def list_suppliers(
    ctx: AuthContext = Depends(require_permission("purchase:read")), db: Session = Depends(get_db)
) -> Any:
    stmt = select(Supplier).where(Supplier.business_id == ctx.business_id).order_by(Supplier.name)
    return db.scalars(stmt).all()


@router.post("/suppliers", response_model=SupplierOut, status_code=status.HTTP_201_CREATED)
def create_supplier(
    body: SupplierIn,
    ctx: AuthContext = Depends(require_permission("purchase:write")),
    db: Session = Depends(get_db),
) -> Any:
    supplier = Supplier(business_id=ctx.business_id, **body.model_dump())
    db.add(supplier)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Supplier already exists") from None
    record_audit(
        db,
        business_id=ctx.business_id,
        user_id=ctx.user.id,
        action="supplier.created",
        entity_type="supplier",
        entity_id=supplier.id,
        after={"name": supplier.name},
    )
    db.commit()
    return supplier


@router.patch("/suppliers/{supplier_id}", response_model=SupplierOut)
def update_supplier(
    supplier_id: uuid.UUID,
    body: SupplierUpdate,
    ctx: AuthContext = Depends(require_permission("purchase:write")),
    db: Session = Depends(get_db),
) -> Any:
    supplier = db.get(Supplier, supplier_id)
    if supplier is None or supplier.business_id != ctx.business_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Supplier not found")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(supplier, field, value)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Supplier already exists") from None
    db.commit()
    return supplier


# ---- purchases ----
class PurchaseLineIn(BaseModel):
    variant_id: uuid.UUID
    quantity: int = Field(ge=1, le=100_000)
    unit_cost: Cost


class PurchaseIn(BaseModel):
    store_id: uuid.UUID
    supplier_id: uuid.UUID
    bill_number: str = Field(min_length=1, max_length=50)
    bill_date: date
    notes: str | None = Field(default=None, max_length=1000)
    items: list[PurchaseLineIn] = Field(min_length=1, max_length=500)


class PurchaseLineOut(BaseModel):
    variant_id: uuid.UUID
    product_name: str
    variant_label: str
    sku: str
    quantity: int
    unit_cost: Decimal
    line_total: Decimal


class PurchaseOut(BaseModel):
    id: uuid.UUID
    store_id: uuid.UUID
    supplier_id: uuid.UUID
    bill_number: str
    bill_date: date
    status: str
    total: Decimal
    notes: str | None
    received_at: datetime | None
    items: list[PurchaseLineOut]


def _out(db: Session, p: Purchase) -> PurchaseOut:
    rows = db.execute(
        select(PurchaseItem, ProductVariant, Product.name)
        .join(ProductVariant, ProductVariant.id == PurchaseItem.variant_id)
        .join(Product, Product.id == ProductVariant.product_id)
        .where(PurchaseItem.purchase_id == p.id)
        .order_by(Product.name, ProductVariant.size, ProductVariant.colour)
    ).all()
    return PurchaseOut(
        id=p.id,
        store_id=p.store_id,
        supplier_id=p.supplier_id,
        bill_number=p.bill_number,
        bill_date=p.bill_date,
        status=p.status,
        total=p.total,
        notes=p.notes,
        received_at=p.received_at,
        items=[
            PurchaseLineOut(
                variant_id=v.id,
                product_name=name,
                variant_label=" / ".join(x for x in (v.size, v.colour) if x) or "Default",
                sku=v.sku,
                quantity=i.quantity,
                unit_cost=i.unit_cost,
                line_total=i.line_total,
            )
            for i, v, name in rows
        ],
    )


def _get(db: Session, ctx: AuthContext, purchase_id: uuid.UUID, lock: bool = False) -> Purchase:
    stmt = select(Purchase).where(Purchase.id == purchase_id)
    purchase = db.scalars(stmt.with_for_update() if lock else stmt).first()
    if purchase is None or purchase.business_id != ctx.business_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Purchase not found")
    ctx.require_store(purchase.store_id)
    return purchase


@router.post("/purchases", response_model=PurchaseOut, status_code=status.HTTP_201_CREATED)
def create_purchase(
    body: PurchaseIn,
    ctx: AuthContext = Depends(require_permission("purchase:write")),
    db: Session = Depends(get_db),
) -> PurchaseOut:
    ctx.require_store(body.store_id)
    supplier = db.get(Supplier, body.supplier_id)
    if supplier is None or supplier.business_id != ctx.business_id or not supplier.is_active:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Unknown supplier")
    ids = [i.variant_id for i in body.items]
    if len(set(ids)) != len(ids):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Each variant may appear once")
    found = db.scalars(
        select(ProductVariant.id).where(
            ProductVariant.id.in_(ids), ProductVariant.business_id == ctx.business_id
        )
    ).all()
    if len(found) != len(ids):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Unknown product variant")
    lines = [(i, gst.money(i.unit_cost * i.quantity)) for i in body.items]
    purchase = Purchase(
        business_id=ctx.business_id,
        store_id=body.store_id,
        supplier_id=body.supplier_id,
        bill_number=body.bill_number.strip(),
        bill_date=body.bill_date,
        notes=body.notes,
        total=sum((t for _, t in lines), Decimal("0.00")),
        created_by=ctx.user.id,
    )
    db.add(purchase)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "This supplier bill number was already entered"
        ) from None
    db.add_all(
        PurchaseItem(
            purchase_id=purchase.id,
            variant_id=i.variant_id,
            quantity=i.quantity,
            unit_cost=i.unit_cost,
            line_total=total,
        )
        for i, total in lines
    )
    record_audit(
        db,
        business_id=ctx.business_id,
        user_id=ctx.user.id,
        action="purchase.created",
        entity_type="purchase",
        entity_id=purchase.id,
        after={"bill": purchase.bill_number, "total": str(purchase.total)},
    )
    db.commit()
    return _out(db, purchase)


@router.get("/purchases", response_model=list[PurchaseOut])
def list_purchases(
    store_id: uuid.UUID,
    status_filter: str | None = Query(default=None, alias="status", pattern="^(draft|received)$"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    ctx: AuthContext = Depends(require_permission("purchase:read")),
    db: Session = Depends(get_db),
) -> list[PurchaseOut]:
    ctx.require_store(store_id)
    stmt = select(Purchase).where(
        Purchase.business_id == ctx.business_id, Purchase.store_id == store_id
    )
    if status_filter:
        stmt = stmt.where(Purchase.status == status_filter)
    stmt = stmt.order_by(Purchase.bill_date.desc(), Purchase.created_at.desc())
    return [_out(db, p) for p in db.scalars(stmt.limit(limit).offset(offset))]


@router.get("/purchases/{purchase_id}", response_model=PurchaseOut)
def get_purchase(
    purchase_id: uuid.UUID,
    ctx: AuthContext = Depends(require_permission("purchase:read")),
    db: Session = Depends(get_db),
) -> PurchaseOut:
    return _out(db, _get(db, ctx, purchase_id))


@router.post("/purchases/{purchase_id}/receive", response_model=PurchaseOut)
def receive_purchase(
    purchase_id: uuid.UUID,
    ctx: AuthContext = Depends(require_permission("purchase:write")),
    db: Session = Depends(get_db),
) -> PurchaseOut:
    """Books the goods in: one `purchase` ledger movement per line, plus the latest unit cost.
    The purchase row is locked, so two simultaneous receipts cannot add the stock twice."""
    purchase = _get(db, ctx, purchase_id, lock=True)
    if purchase.status != "draft":
        raise HTTPException(status.HTTP_409_CONFLICT, "This purchase was already received")
    for item in db.scalars(select(PurchaseItem).where(PurchaseItem.purchase_id == purchase.id)):
        apply_movement(
            db,
            business_id=ctx.business_id,
            store_id=purchase.store_id,
            variant_id=item.variant_id,
            movement_type="purchase",
            delta=item.quantity,
            user_id=ctx.user.id,
            reference_type="purchase",
            reference_id=purchase.id,
        )
        variant = db.get(ProductVariant, item.variant_id)
        assert variant is not None
        variant.cost_price = item.unit_cost  # last purchase cost feeds margin reports
    purchase.status = "received"
    purchase.received_by = ctx.user.id
    purchase.received_at = datetime.now(UTC)
    record_audit(
        db,
        business_id=ctx.business_id,
        user_id=ctx.user.id,
        action="purchase.received",
        entity_type="purchase",
        entity_id=purchase.id,
        after={"bill": purchase.bill_number, "total": str(purchase.total)},
    )
    db.commit()
    return _out(db, purchase)


@router.delete("/purchases/{purchase_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_draft_purchase(
    purchase_id: uuid.UUID,
    ctx: AuthContext = Depends(require_permission("purchase:write")),
    db: Session = Depends(get_db),
) -> None:
    purchase = _get(db, ctx, purchase_id, lock=True)
    if purchase.status != "draft":
        raise HTTPException(status.HTTP_409_CONFLICT, "A received purchase cannot be deleted")
    record_audit(
        db,
        business_id=ctx.business_id,
        user_id=ctx.user.id,
        action="purchase.deleted",
        entity_type="purchase",
        entity_id=purchase.id,
        before={"bill": purchase.bill_number, "total": str(purchase.total)},
    )
    db.delete(purchase)
    db.commit()
