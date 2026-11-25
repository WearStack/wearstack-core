"""Offline sales arriving from devices.

An offline sale already happened: the customer has the goods and has paid. So the server never
silently drops or rewrites one. Each is either applied (a real sale with a final GST invoice), or
held as a *conflict* for a manager, or marked *failed* with the reason, and every outcome is kept.
The client_operation_id is the idempotency key, so a retried request always gets the same answer.
"""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import AuthContext
from app.core.config import get_settings
from app.models import (
    Device,
    Inventory,
    Product,
    ProductVariant,
    Role,
    Sale,
    SyncOperation,
    User,
)
from app.modules.sales.schemas import SaleIn, SaleLineIn
from app.modules.sync.schemas import SyncSaleIn
from app.services.audit import record_audit
from app.services.rbac import accessible_store_ids, permission_codes
from app.services.sales import SaleError, SaleOptions, create_sale, find_existing

FUTURE_TOLERANCE = timedelta(minutes=5)  # device clocks drift a little


class Rejected(Exception):
    """The operation cannot be applied as sent (a failure, not a conflict)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def context_for(db: Session, business_id: uuid.UUID, user_id: uuid.UUID) -> AuthContext | None:
    """The authorisation context of a user, as if they had made the request themselves."""
    user = db.get(User, user_id)
    if user is None or user.business_id != business_id or not user.is_active:
        return None
    role = db.get(Role, user.role_id)
    if role is None:
        return None
    return AuthContext(
        user=user,
        role=role,
        permissions=permission_codes(db, role.id),
        store_ids=accessible_store_ids(db, user, role),
    )


def _label(v: ProductVariant) -> str:
    return " / ".join(x for x in (v.size, v.colour) if x) or "Default"


def _price(variant: ProductVariant, product: Product) -> Decimal:
    return variant.selling_price if variant.selling_price is not None else product.selling_price


def receive_sale(
    db: Session, syncer: AuthContext, device: Device, data: SyncSaleIn
) -> SyncOperation:
    """Stores the operation and decides it. Safe to call again with the same operation id."""
    existing = _find(db, syncer.business_id, data.client_operation_id)
    if existing is not None:
        # Already decided, or being decided right now by another request: same answer.
        return existing
    now = datetime.now(UTC)
    op = SyncOperation(
        business_id=syncer.business_id,
        store_id=data.store_id,
        device_id=device.id,
        client_operation_id=data.client_operation_id,
        provisional_number=data.provisional_number,
        cashier_id=data.cashier_id,
        sold_at=data.sold_at,
        payload=data.model_dump(mode="json"),
        status="received",
        conflicts=[],
        received_by=syncer.user.id,
        received_at=now,
    )
    db.add(op)
    try:
        db.commit()  # the operation is on record before anything else happens to it
    except IntegrityError:
        db.rollback()  # a concurrent retry stored it first
        found = _find(db, syncer.business_id, data.client_operation_id)
        if found is None:
            raise
        return found
    return attempt(db, op)


def _find(db: Session, business_id: uuid.UUID, client_op: uuid.UUID) -> SyncOperation | None:
    return db.scalars(
        select(SyncOperation).where(
            SyncOperation.business_id == business_id,
            SyncOperation.client_operation_id == client_op,
        )
    ).first()


def attempt(
    db: Session,
    op: SyncOperation,
    *,
    accept: bool = False,
    resolver: AuthContext | None = None,
) -> SyncOperation:
    """Tries to turn the operation into a sale. With accept=True (a manager's decision) it books
    the sale as charged, even if prices changed or stock ran short; a stock shortfall is fixed by
    a visible, reasoned stock adjustment."""
    data = SyncSaleIn.model_validate(op.payload)
    now = datetime.now(UTC)
    try:
        sale, replayed, conflicts = _apply(db, op, data, now, accept, resolver)
    except Rejected as e:
        return _finish(db, op, "failed", now, error=(e.code, e.message))
    except SaleError as e:
        return _finish(db, op, "failed", now, error=(e.code, e.message))
    if conflicts:
        return _finish(db, op, "conflict", now, conflicts=conflicts)
    assert sale is not None
    op.sale_id = sale.id
    return _finish(db, op, "applied", now, replayed=replayed)


def _apply(
    db: Session,
    op: SyncOperation,
    data: SyncSaleIn,
    now: datetime,
    accept: bool,
    resolver: AuthContext | None,
) -> tuple[Sale | None, bool, list[dict[str, Any]]]:
    settings = get_settings()
    cashier = context_for(db, op.business_id, data.cashier_id)
    if cashier is None:
        raise Rejected("cashier_invalid", "The cashier on this sale is not an active user")
    if "sale:create" not in cashier.permissions:
        raise Rejected("cashier_not_allowed", "The cashier is not allowed to make sales")
    if data.store_id not in cashier.store_ids:
        raise Rejected("cashier_no_store", "The cashier has no access to this store")
    if data.sold_at > now + FUTURE_TOLERANCE:
        raise Rejected(
            "sold_at_in_future", "The sale is dated in the future (check the device clock)"
        )

    # A sale that was already recorded online (the connection dropped before the reply arrived).
    already = find_existing(db, op.business_id, data.client_operation_id)
    if already is not None:
        return already, True, []

    conflicts: list[dict[str, Any]] = []
    prices: list[Decimal] = []
    if not accept and data.sold_at < now - timedelta(days=settings.offline_max_sale_age_days):
        conflicts.append(
            {
                "code": "sale_too_old",
                "sold_at": data.sold_at.isoformat(),
                "max_days": settings.offline_max_sale_age_days,
            }
        )
    for line in data.items:
        variant = db.get(ProductVariant, line.variant_id)
        product = db.get(Product, variant.product_id) if variant else None
        if variant is None or product is None or variant.business_id != op.business_id:
            raise Rejected("unknown_variant", "A product on this sale no longer exists")
        prices.append(line.unit_price)
        if accept:
            continue
        base = {
            "variant_id": str(variant.id),
            "product_name": product.name,
            "variant_label": _label(variant),
        }
        if not (variant.is_active and product.is_active):
            conflicts.append({"code": "product_inactive", **base})
        current = _price(variant, product)
        if line.unit_price != current:
            conflicts.append(
                {
                    "code": "price_changed",
                    **base,
                    "charged": str(line.unit_price),
                    "current": str(current),
                }
            )
    if conflicts:
        return None, False, conflicts

    options = SaleOptions(
        unit_prices=prices,
        allow_inactive=accept,
        shortfall_reason=(
            f"Offline sale {op.provisional_number or str(op.client_operation_id)[:8]} synced after "
            "stock had run out; accepted by a manager"
        )
        if accept
        else None,
        resolver_id=resolver.user.id if resolver else None,
    )
    body = SaleIn(
        idempotency_key=data.client_operation_id,
        store_id=data.store_id,
        customer_id=data.customer_id,
        items=[
            SaleLineIn(variant_id=i.variant_id, quantity=i.quantity, discount=i.discount)
            for i in data.items
        ],
        payments=data.payments,
    )
    try:
        sale, replayed = create_sale(
            db, cashier, body, now=data.sold_at, issued_at=now, options=options
        )
    except SaleError as e:
        if e.code == "insufficient_stock":
            return None, False, _shortages(db, data)
        raise
    return sale, replayed, []


def _shortages(db: Session, data: SyncSaleIn) -> list[dict[str, Any]]:
    """Every variant on the sale that the system currently holds too little of."""
    wanted: dict[uuid.UUID, int] = {}
    for line in data.items:
        wanted[line.variant_id] = wanted.get(line.variant_id, 0) + line.quantity
    out: list[dict[str, Any]] = []
    for variant_id, requested in wanted.items():
        inv = db.get(Inventory, (variant_id, data.store_id))
        available = inv.quantity if inv else 0
        if requested > available:
            variant = db.get(ProductVariant, variant_id)
            product = db.get(Product, variant.product_id) if variant else None
            out.append(
                {
                    "code": "insufficient_stock",
                    "variant_id": str(variant_id),
                    "product_name": product.name if product else "Unknown",
                    "variant_label": _label(variant) if variant else "",
                    "requested": requested,
                    "available": available,
                }
            )
    return out


def _finish(
    db: Session,
    op: SyncOperation,
    status: str,
    now: datetime,
    *,
    conflicts: list[dict[str, Any]] | None = None,
    error: tuple[str, str] | None = None,
    replayed: bool = False,
) -> SyncOperation:
    op.status = status
    op.processed_at = now
    op.conflicts = conflicts or []
    op.error_code, op.error_message = error if error else (None, None)
    if status != "applied":
        record_audit(
            db,
            business_id=op.business_id,
            user_id=op.received_by,
            action=f"sync.{status}",
            entity_type="sync_operation",
            entity_id=op.id,
            after={
                "provisional": op.provisional_number,
                "conflicts": [c["code"] for c in op.conflicts],
                "error": op.error_code,
            },
        )
    db.commit()
    return op


def resolve(
    db: Session, resolver: AuthContext, op: SyncOperation, action: str, note: str | None
) -> SyncOperation:
    """A manager's decision on a conflict or failure: accept, reject, or retry."""
    if op.status not in ("conflict", "failed"):
        raise Rejected("not_pending", f"This operation is already {op.status}")
    before = {"status": op.status, "conflicts": [c["code"] for c in op.conflicts]}
    if action == "reject":
        if not (note and note.strip()):
            raise Rejected("note_required", "Say why this sale is being rejected")
        op.status = "rejected"
    elif action == "accept":
        if op.status != "conflict":
            raise Rejected(
                "not_acceptable", "Only a conflict can be accepted; fix a failure or reject it"
            )
        attempt(db, op, accept=True, resolver=resolver)
    else:
        attempt(db, op)
    op.resolved_by = resolver.user.id
    op.resolved_at = datetime.now(UTC)
    op.resolution_note = note.strip() if note else None
    record_audit(
        db,
        business_id=op.business_id,
        user_id=resolver.user.id,
        action=f"sync.{action}",
        entity_type="sync_operation",
        entity_id=op.id,
        before=before,
        after={
            "status": op.status,
            "note": op.resolution_note,
            "sale_id": str(op.sale_id) if op.sale_id else None,
        },
    )
    db.commit()
    return op
