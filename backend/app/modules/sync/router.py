import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, require_permission
from app.core.config import get_settings
from app.db.session import get_db
from app.models import (
    Category,
    Customer,
    Device,
    GstDocument,
    Inventory,
    Product,
    ProductVariant,
    Store,
    SyncOperation,
    User,
)
from app.modules.sync.schemas import (
    CatalogCustomer,
    CatalogOut,
    CatalogSettings,
    CatalogVariant,
    DeviceIn,
    DeviceOut,
    OperationLine,
    OperationOut,
    ResolveIn,
    SyncBatchIn,
    SyncBatchOut,
    SyncResultOut,
)
from app.services import gst
from app.services.sales import IST
from app.services.sync import Rejected, receive_sale, resolve
from app.services.tax import load_rates, pick_rate

router = APIRouter(tags=["sync"])


def _now() -> datetime:
    return datetime.now(UTC)


# ---- devices ----
@router.post("/devices", response_model=DeviceOut)
def register_device(
    body: DeviceIn,
    ctx: AuthContext = Depends(require_permission("sale:create")),
    db: Session = Depends(get_db),
) -> Device:
    """Registers (or re-identifies) this browser as a POS device. Idempotent."""
    ctx.require_store(body.store_id)
    device = db.scalars(
        select(Device).where(
            Device.business_id == ctx.business_id, Device.identifier == body.identifier
        )
    ).first()
    if device is None:
        device = Device(
            business_id=ctx.business_id,
            identifier=body.identifier,
            store_id=body.store_id,
            name=body.name,
        )
        db.add(device)
    elif not device.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This device has been disabled")
    else:
        device.name, device.store_id = body.name, body.store_id
    device.last_seen_at = _now()
    db.commit()
    return device


@router.get("/devices", response_model=list[DeviceOut])
def list_devices(
    ctx: AuthContext = Depends(require_permission("sync:resolve")), db: Session = Depends(get_db)
) -> list[Device]:
    stmt = select(Device).where(
        Device.business_id == ctx.business_id, Device.store_id.in_(ctx.store_ids)
    )
    return list(db.scalars(stmt.order_by(Device.name)))


def _device(db: Session, ctx: AuthContext, device_id: uuid.UUID) -> Device:
    device = db.get(Device, device_id)
    if device is None or device.business_id != ctx.business_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown device: register it first")
    if not device.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This device has been disabled")
    ctx.require_store(device.store_id)
    return device


# ---- catalogue snapshot ----
@router.get("/sync/catalog", response_model=CatalogOut)
def catalog(
    store_id: uuid.UUID,
    device_id: uuid.UUID | None = None,
    ctx: AuthContext = Depends(require_permission("sale:create")),
    db: Session = Depends(get_db),
) -> CatalogOut:
    """Everything an offline till needs: sellable products with prices, barcodes and the stock this
    store holds, plus customers. Prices are tax-inclusive, exactly as the online till charges."""
    ctx.require_store(store_id)
    store = db.get(Store, store_id)
    assert store is not None
    if device_id:
        device = _device(db, ctx, device_id)
        device.last_seen_at = _now()
        db.commit()
    s = get_settings()
    today = datetime.now(UTC).astimezone(IST).date()
    rates = load_rates(db, ctx.business_id)
    stock = {
        i.variant_id: i.quantity
        for i in db.scalars(select(Inventory).where(Inventory.store_id == store_id))
    }
    categories = {
        c.id: c.name
        for c in db.scalars(select(Category).where(Category.business_id == ctx.business_id))
    }
    rows = db.execute(
        select(ProductVariant, Product)
        .join(Product, Product.id == ProductVariant.product_id)
        .where(ProductVariant.business_id == ctx.business_id)
        .order_by(Product.name, ProductVariant.size, ProductVariant.colour)
    ).all()
    variants = []
    for v, p in rows:
        price = v.selling_price if v.selling_price is not None else p.selling_price
        has_rate = pick_rate(rates, p.tax_rate_id, today, price) is not None
        variants.append(
            CatalogVariant(
                id=v.id, product_id=p.id, product_name=p.name,
                category=categories.get(p.category_id) if p.category_id else None,
                size=v.size, colour=v.colour, sku=v.sku, barcode=v.barcode, price=price,
                hsn_code=p.hsn_code, quantity=stock.get(v.id, 0),
                sellable=bool(v.is_active and p.is_active and has_rate),
            )
        )  # fmt: skip
    customers = []
    if "customer:read" in ctx.permissions:
        customers = [
            CatalogCustomer(id=c.id, name=c.name, phone=c.phone, state_code=c.state_code)
            for c in db.scalars(
                select(Customer)
                .where(Customer.business_id == ctx.business_id, Customer.is_active.is_(True))
                .order_by(Customer.name)
            )
        ]
    return CatalogOut(
        generated_at=datetime.now(UTC),
        store_id=store_id,
        store_name=store.name,
        settings=CatalogSettings(
            free_discount_percent=s.free_discount_percent,
            offline_warn_hours=s.offline_warn_hours,
            offline_block_hours=s.offline_block_hours,
            offline_max_sale_age_days=s.offline_max_sale_age_days,
            sync_batch_max=s.sync_batch_max,
        ),
        variants=variants,
        customers=customers,
    )


# ---- batch sync ----
def _result(db: Session, op: SyncOperation) -> SyncResultOut:
    number = None
    if op.sale_id:
        number = db.scalars(
            select(GstDocument.number).where(GstDocument.sale_id == op.sale_id)
        ).first()
    return SyncResultOut(
        operation_id=op.id,
        client_operation_id=op.client_operation_id,
        status=op.status,
        sale_id=op.sale_id,
        invoice_number=number,
        conflicts=op.conflicts,
        error_code=op.error_code,
        error_message=op.error_message,
    )


@router.post("/sync/sales", response_model=SyncBatchOut)
def sync_sales(
    body: SyncBatchIn,
    ctx: AuthContext = Depends(require_permission("sale:create")),
    db: Session = Depends(get_db),
) -> SyncBatchOut:
    """Applies a device's queued sales, one at a time and independently: a problem with one never
    blocks the others. Sending the same sale again returns the same answer."""
    limit = get_settings().sync_batch_max
    if len(body.operations) > limit:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, f"At most {limit} sales per request"
        )
    device = _device(db, ctx, body.device_id)
    if any(o.store_id != device.store_id for o in body.operations):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "A sale belongs to a different store than this device",
        )
    device.last_seen_at = _now()
    db.commit()
    return SyncBatchOut(
        results=[_result(db, receive_sale(db, ctx, device, o)) for o in body.operations]
    )


# ---- status screen ----
def _total(payload: dict[str, Any]) -> Decimal:
    gross = sum(
        (
            Decimal(i["unit_price"]) * i["quantity"] - Decimal(i.get("discount", "0"))
            for i in payload["items"]
        ),
        Decimal("0"),
    )
    return gst.round_to_rupee(gross)[0]


def _out(db: Session, op: SyncOperation, with_lines: bool = False) -> OperationOut:
    device = db.get(Device, op.device_id)
    cashier = db.get(User, op.cashier_id)
    number = None
    if op.sale_id:
        number = db.scalars(
            select(GstDocument.number).where(GstDocument.sale_id == op.sale_id)
        ).first()
    lines: list[OperationLine] = []
    if with_lines:
        for i in op.payload["items"]:
            v = db.get(ProductVariant, uuid.UUID(i["variant_id"]))
            p = db.get(Product, v.product_id) if v else None
            lines.append(
                OperationLine(
                    variant_id=uuid.UUID(i["variant_id"]),
                    product_name=p.name if p else "Unknown",
                    variant_label=" / ".join(x for x in (v.size, v.colour) if x) if v else "",
                    quantity=i["quantity"],
                    unit_price=Decimal(i["unit_price"]),
                    discount=Decimal(i.get("discount", "0")),
                )
            )
    return OperationOut(
        id=op.id,
        client_operation_id=op.client_operation_id,
        provisional_number=op.provisional_number,
        status=op.status,
        sold_at=op.sold_at,
        received_at=op.received_at,
        processed_at=op.processed_at,
        store_id=op.store_id,
        device_id=op.device_id,
        device_name=device.name if device else None,
        cashier_id=op.cashier_id,
        cashier_name=cashier.full_name if cashier else None,
        total=_total(op.payload),
        sale_id=op.sale_id,
        invoice_number=number,
        conflicts=op.conflicts,
        error_code=op.error_code,
        error_message=op.error_message,
        resolution_note=op.resolution_note,
        lines=lines,
    )


def _visible(ctx: AuthContext, op: SyncOperation) -> bool:
    return "sync:resolve" in ctx.permissions or ctx.user.id in (op.cashier_id, op.received_by)


@router.get("/sync/operations", response_model=list[OperationOut])
def list_operations(
    store_id: uuid.UUID,
    status_filter: str | None = Query(
        default=None, alias="status", pattern="^(received|applied|conflict|failed|rejected)$"
    ),
    limit: int = Query(100, ge=1, le=300),
    ctx: AuthContext = Depends(require_permission("sale:create")),
    db: Session = Depends(get_db),
) -> list[OperationOut]:
    """Managers see every device's sales for the store; a cashier sees only their own."""
    ctx.require_store(store_id)
    stmt = select(SyncOperation).where(
        SyncOperation.business_id == ctx.business_id, SyncOperation.store_id == store_id
    )
    if "sync:resolve" not in ctx.permissions:
        stmt = stmt.where(
            (SyncOperation.cashier_id == ctx.user.id) | (SyncOperation.received_by == ctx.user.id)
        )
    if status_filter:
        stmt = stmt.where(SyncOperation.status == status_filter)
    ops = db.scalars(stmt.order_by(SyncOperation.sold_at.desc()).limit(limit))
    return [_out(db, o) for o in ops]


def _get(db: Session, ctx: AuthContext, op_id: uuid.UUID) -> SyncOperation:
    op = db.get(SyncOperation, op_id)
    if op is None or op.business_id != ctx.business_id or not _visible(ctx, op):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Operation not found")
    ctx.require_store(op.store_id)
    return op


@router.get("/sync/operations/{op_id}", response_model=OperationOut)
def get_operation(
    op_id: uuid.UUID,
    ctx: AuthContext = Depends(require_permission("sale:create")),
    db: Session = Depends(get_db),
) -> OperationOut:
    return _out(db, _get(db, ctx, op_id), with_lines=True)


@router.post("/sync/operations/{op_id}/resolve", response_model=OperationOut)
def resolve_operation(
    op_id: uuid.UUID,
    body: ResolveIn,
    ctx: AuthContext = Depends(require_permission("sync:resolve")),
    db: Session = Depends(get_db),
) -> OperationOut:
    op = _get(db, ctx, op_id)
    try:
        resolve(db, ctx, op, body.action, body.note)
    except Rejected as e:
        raise HTTPException(status.HTTP_409_CONFLICT, e.message) from None
    return _out(db, op, with_lines=True)
