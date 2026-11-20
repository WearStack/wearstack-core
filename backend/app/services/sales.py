import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import AuthContext
from app.core.config import get_settings
from app.models import (
    Business,
    Customer,
    GstDocument,
    Payment,
    Product,
    ProductVariant,
    Sale,
    SaleItem,
    Store,
)
from app.modules.sales.schemas import SaleIn
from app.services import gst
from app.services.audit import record_audit
from app.services.inventory import InsufficientStock, apply_movement
from app.services.invoice_numbers import next_number
from app.services.tax import resolve_tax_rate

IST = ZoneInfo("Asia/Kolkata")
ZERO = Decimal("0.00")


@dataclass
class PricedSale:
    """Everything about a sale that can be known before any money or stock moves."""

    store: Store
    business: Business
    customer: Customer | None
    now: datetime
    place_of_supply: str
    interstate: bool
    lines: list[tuple[SaleItem, ProductVariant]]
    discount_total: Decimal
    taxable_total: Decimal
    cgst_total: Decimal
    sgst_total: Decimal
    igst_total: Decimal
    round_off: Decimal
    grand_total: Decimal


class SaleError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def find_existing(db: Session, business_id: uuid.UUID, key: uuid.UUID) -> Sale | None:
    return db.scalars(
        select(Sale).where(Sale.business_id == business_id, Sale.idempotency_key == key)
    ).first()


def _label(v: ProductVariant) -> str:
    return " / ".join(x for x in (v.size, v.colour) if x) or "Default"


def create_sale(
    db: Session, ctx: AuthContext, body: SaleIn, now: datetime | None = None
) -> tuple[Sale, bool]:
    """Creates a finalised sale in one transaction: stock, tax, invoice number, payments.
    Returns (sale, replayed). A retry with the same idempotency key returns the first result."""
    existing = find_existing(db, ctx.business_id, body.idempotency_key)
    if existing:
        if existing.store_id != body.store_id:
            raise SaleError(409, "This idempotency key was already used for a different sale")
        return existing, True
    try:
        sale = _create(db, ctx, body, now)
        db.commit()
        return sale, False
    except IntegrityError:
        # A concurrent request with the same key won the race; its sale is the answer.
        db.rollback()
        existing = find_existing(db, ctx.business_id, body.idempotency_key)
        if existing is None:
            raise
        return existing, True
    except Exception:
        db.rollback()
        raise


def price_sale(
    db: Session, ctx: AuthContext, body: SaleIn, now: datetime | None = None
) -> PricedSale:
    """Validates the basket and computes prices, GST and totals. Writes nothing."""
    settings = get_settings()
    ctx.require_store(body.store_id)
    store = db.get(Store, body.store_id)
    business = db.get(Business, ctx.business_id)
    if store is None or business is None or store.business_id != ctx.business_id:
        raise SaleError(404, "Store not found")
    if not store.is_active:
        raise SaleError(409, "This store is inactive")
    if not (store.gstin or business.gstin):
        # A GST invoice must carry the seller's GSTIN, and an unregistered seller cannot charge GST.
        raise SaleError(
            409, "Add your GSTIN in Stores before billing: a GST invoice needs the seller's GSTIN"
        )

    customer: Customer | None = None
    if body.customer_id:
        customer = db.get(Customer, body.customer_id)
        if customer is None or customer.business_id != ctx.business_id or not customer.is_active:
            raise SaleError(422, "Unknown customer")

    now = now or datetime.now(IST)  # tests and the demo seed pass a fixed time
    on = now.date()
    place_of_supply = (customer.state_code if customer and customer.state_code else None) or (
        store.state_code
    )
    interstate = place_of_supply != store.state_code

    lines: list[tuple[SaleItem, ProductVariant]] = []
    for item in body.items:
        variant = db.get(ProductVariant, item.variant_id)
        product = db.get(Product, variant.product_id) if variant else None
        if variant is None or product is None or variant.business_id != ctx.business_id:
            raise SaleError(422, "Unknown product variant")
        if not (variant.is_active and product.is_active):
            raise SaleError(409, f"{product.name} is no longer available")
        unit_price = (
            variant.selling_price if variant.selling_price is not None else product.selling_price
        )
        gross = gst.money(unit_price * item.quantity)
        discount = gst.money(item.discount)
        if discount > gross:
            raise SaleError(422, f"Discount exceeds the line amount for {product.name}")
        limit = gst.money(gross * settings.free_discount_percent / 100)
        if discount > limit and "sale:discount" not in ctx.permissions:
            raise SaleError(
                403,
                f"Discounts above {settings.free_discount_percent}% "
                "need the sale:discount permission",
            )
        if product.tax_rate_id is None:
            raise SaleError(422, f"{product.name} has no GST rate configured")
        slab_price = gst.slab_unit_price(
            unit_price, item.quantity, discount, settings.gst_slab_basis
        )
        rate = resolve_tax_rate(db, product.tax_rate_id, on, slab_price)
        if rate is None:
            raise SaleError(
                422, f"No GST rate is in force for {product.name} at this price on {on.isoformat()}"
            )
        tax = gst.split_inclusive(gross - discount, rate.rate, interstate)
        lines.append(
            (
                SaleItem(
                    variant_id=variant.id,
                    product_name=product.name,
                    variant_label=_label(variant),
                    sku=variant.sku,
                    hsn_code=product.hsn_code,
                    line_no=len(lines) + 1,
                    quantity=item.quantity,
                    unit_price=unit_price,
                    discount=discount,
                    unit_cost=variant.cost_price
                    if variant.cost_price is not None
                    else product.cost_price,
                    tax_rate=rate.rate,
                    tax_rate_id=rate.id,
                    taxable_value=tax.taxable,
                    cgst=tax.cgst,
                    sgst=tax.sgst,
                    igst=tax.igst,
                    line_total=tax.gross,
                ),
                variant,
            )
        )

    items = [i for i, _ in lines]
    subtotal = sum((i.line_total for i in items), ZERO)
    grand_total, round_off = gst.round_to_rupee(subtotal)
    return PricedSale(
        store=store,
        business=business,
        customer=customer,
        now=now,
        place_of_supply=place_of_supply,
        interstate=interstate,
        lines=lines,
        discount_total=sum((i.discount for i in items), ZERO),
        taxable_total=sum((i.taxable_value for i in items), ZERO),
        cgst_total=sum((i.cgst for i in items), ZERO),
        sgst_total=sum((i.sgst for i in items), ZERO),
        igst_total=sum((i.igst for i in items), ZERO),
        round_off=round_off,
        grand_total=grand_total,
    )


def _create(db: Session, ctx: AuthContext, body: SaleIn, now: datetime | None = None) -> Sale:
    priced = price_sale(db, ctx, body, now)
    store, business, customer = priced.store, priced.business, priced.customer
    lines, now = priced.lines, priced.now
    items = [i for i, _ in lines]
    grand_total = priced.grand_total

    paid = sum((p.amount for p in body.payments), ZERO)
    if paid != grand_total:
        raise SaleError(
            422, f"Payments total {paid} but the sale total is {grand_total}; they must match"
        )

    sale = Sale(
        business_id=ctx.business_id,
        store_id=store.id,
        customer_id=customer.id if customer else None,
        user_id=ctx.user.id,
        idempotency_key=body.idempotency_key,
        sold_at=now,
        place_of_supply=priced.place_of_supply,
        is_interstate=priced.interstate,
        discount_total=priced.discount_total,
        taxable_total=priced.taxable_total,
        cgst_total=priced.cgst_total,
        sgst_total=priced.sgst_total,
        igst_total=priced.igst_total,
        round_off=priced.round_off,
        grand_total=grand_total,
    )
    db.add(sale)
    db.flush()  # the idempotency unique constraint fires here, before any stock is touched

    for line, variant in lines:
        line.sale_id = sale.id
        db.add(line)
        try:
            apply_movement(
                db,
                business_id=ctx.business_id,
                store_id=store.id,
                variant_id=variant.id,
                movement_type="sale",
                delta=-line.quantity,
                user_id=ctx.user.id,
                reference_type="sale",
                reference_id=sale.id,
            )
        except InsufficientStock as e:
            raise SaleError(
                409, f"Not enough stock for {line.product_name} ({line.variant_label}): {e}"
            ) from None
    for p in body.payments:
        db.add(
            Payment(
                business_id=ctx.business_id,
                sale_id=sale.id,
                method=p.method,
                amount=p.amount,
                status="confirmed",  # the cashier confirmed it and supplied the reference
                reference=p.reference.strip() if p.reference else None,
            )
        )

    fy = gst.financial_year(now.date())
    number = next_number(
        db,
        business_id=ctx.business_id,
        store_id=store.id,
        store_code=store.code,
        doc_type="invoice",
        financial_year=fy,
    )
    db.add(
        GstDocument(
            business_id=ctx.business_id,
            store_id=store.id,
            sale_id=sale.id,
            doc_type="invoice",
            number=number,
            financial_year=fy,
            issued_at=now,
            seller={
                "business_name": business.legal_name or business.name,
                "gstin": store.gstin or business.gstin,
                "store_name": store.name,
                "store_code": store.code,
                "address": store.address,
                "state_code": store.state_code,
            },
            buyer={
                "name": customer.name if customer else "Walk-in customer",
                "phone": customer.phone if customer else None,
                "gstin": customer.gstin if customer else None,
                "state_code": priced.place_of_supply,
            },
        )
    )
    record_audit(
        db,
        business_id=ctx.business_id,
        user_id=ctx.user.id,
        action="sale.created",
        entity_type="sale",
        entity_id=sale.id,
        after={"invoice": number, "total": str(grand_total), "lines": len(items)},
    )
    db.flush()
    return sale
