import uuid
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, require_permission
from app.db.session import get_db
from app.models import GstDocument, Payment, Sale, SaleItem
from app.modules.sales.schemas import (
    QuoteIn,
    QuoteLine,
    SaleIn,
    SaleItemOut,
    SaleOut,
    SalePaymentOut,
    SaleQuote,
    SaleSummary,
)
from app.services.invoice_pdf import build_invoice_pdf
from app.services.sales import SaleError, create_sale, price_sale

router = APIRouter(prefix="/sales", tags=["sales"])
IST = ZoneInfo("Asia/Kolkata")


def _detail(db: Session, sale: Sale, replayed: bool = False) -> SaleOut:
    doc = db.scalars(select(GstDocument).where(GstDocument.sale_id == sale.id)).one()
    items = db.scalars(
        select(SaleItem).where(SaleItem.sale_id == sale.id).order_by(SaleItem.line_no)
    ).all()
    payments = db.scalars(
        select(Payment).where(Payment.sale_id == sale.id).order_by(Payment.method, Payment.amount)
    ).all()
    return SaleOut(
        **{
            f: getattr(sale, f)
            for f in (
                "id",
                "store_id",
                "customer_id",
                "sold_at",
                "place_of_supply",
                "is_interstate",
                "discount_total",
                "taxable_total",
                "cgst_total",
                "sgst_total",
                "igst_total",
                "round_off",
                "grand_total",
            )  # fmt: skip
        },
        invoice_number=doc.number,
        items=[SaleItemOut.model_validate(i) for i in items],
        payments=[SalePaymentOut.model_validate(p) for p in payments],
        replayed=replayed,
    )


def _get_sale(db: Session, ctx: AuthContext, sale_id: uuid.UUID) -> Sale:
    sale = db.get(Sale, sale_id)
    if sale is None or sale.business_id != ctx.business_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Sale not found")
    ctx.require_store(sale.store_id)
    return sale


@router.post("", response_model=SaleOut, status_code=status.HTTP_201_CREATED)
def post_sale(
    body: SaleIn,
    response: Response,
    ctx: AuthContext = Depends(require_permission("sale:create")),
    db: Session = Depends(get_db),
) -> SaleOut:
    try:
        sale, replayed = create_sale(db, ctx, body)
    except SaleError as e:
        raise HTTPException(e.status, e.message) from None
    if replayed:
        response.status_code = status.HTTP_200_OK
    return _detail(db, sale, replayed)


@router.post("/quote", response_model=SaleQuote)
def quote_sale(
    body: QuoteIn,
    ctx: AuthContext = Depends(require_permission("sale:create")),
    db: Session = Depends(get_db),
) -> SaleQuote:
    """Prices a basket exactly as a sale would, without touching stock, numbers or payments.
    Applies the same rules as a sale (stock is checked when the sale is actually made)."""
    try:
        priced = price_sale(
            db, ctx, SaleIn(idempotency_key=uuid.uuid4(), payments=[], **body.model_dump())
        )
    except SaleError as e:
        raise HTTPException(e.status, e.message) from None
    return SaleQuote(
        place_of_supply=priced.place_of_supply,
        is_interstate=priced.interstate,
        lines=[
            QuoteLine(
                variant_id=item.variant_id,
                product_name=item.product_name,
                variant_label=item.variant_label,
                quantity=item.quantity,
                unit_price=item.unit_price,
                discount=item.discount,
                tax_rate=item.tax_rate,
                line_total=item.line_total,
            )
            for item, _ in priced.lines
        ],
        discount_total=priced.discount_total,
        taxable_total=priced.taxable_total,
        cgst_total=priced.cgst_total,
        sgst_total=priced.sgst_total,
        igst_total=priced.igst_total,
        round_off=priced.round_off,
        grand_total=priced.grand_total,
    )


@router.get("", response_model=list[SaleSummary])
def list_sales(
    store_id: uuid.UUID,
    day: date | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    ctx: AuthContext = Depends(require_permission("sale:read")),
    db: Session = Depends(get_db),
) -> list[SaleSummary]:
    ctx.require_store(store_id)
    stmt = select(Sale, GstDocument.number).join(GstDocument, GstDocument.sale_id == Sale.id)
    stmt = stmt.where(Sale.business_id == ctx.business_id, Sale.store_id == store_id)
    if day:
        start = datetime.combine(day, time.min, tzinfo=IST)
        stmt = stmt.where(Sale.sold_at >= start, Sale.sold_at < start + timedelta(days=1))
    rows = db.execute(stmt.order_by(Sale.sold_at.desc()).limit(limit).offset(offset)).all()
    return [
        SaleSummary(
            id=s.id,
            invoice_number=number,
            sold_at=s.sold_at,
            customer_id=s.customer_id,
            grand_total=s.grand_total,
        )
        for s, number in rows
    ]


@router.get("/{sale_id}", response_model=SaleOut)
def get_sale(
    sale_id: uuid.UUID,
    ctx: AuthContext = Depends(require_permission("sale:read")),
    db: Session = Depends(get_db),
) -> SaleOut:
    return _detail(db, _get_sale(db, ctx, sale_id))


@router.get("/{sale_id}/invoice.pdf")
def invoice_pdf(
    sale_id: uuid.UUID,
    ctx: AuthContext = Depends(require_permission("sale:read")),
    db: Session = Depends(get_db),
) -> Response:
    sale = _get_sale(db, ctx, sale_id)
    doc = db.scalars(select(GstDocument).where(GstDocument.sale_id == sale.id)).one()
    items = list(
        db.scalars(select(SaleItem).where(SaleItem.sale_id == sale.id).order_by(SaleItem.line_no))
    )
    payments = list(db.scalars(select(Payment).where(Payment.sale_id == sale.id)))
    filename = doc.number.replace("/", "-")
    return Response(
        build_invoice_pdf(doc, sale, items, payments),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="invoice-{filename}.pdf"'},
    )
