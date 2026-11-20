import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, require_permission
from app.db.session import get_db
from app.models import Brand, Category, TaxRate
from app.modules.catalog.schemas import NameIn, NameOut, TaxRateIn, TaxRateOut
from app.services.audit import record_audit

router = APIRouter(tags=["catalogue"])


def _windows_overlap(a_from: date, a_to: date | None, b_from: date, b_to: date | None) -> bool:
    return a_from <= (b_to or date.max) and b_from <= (a_to or date.max)


def _slabs_overlap(
    a_min: Decimal | None, a_max: Decimal | None, b_min: Decimal | None, b_max: Decimal | None
) -> bool:
    """Slabs are (min, max]; NULL bounds are open. Two slabs overlap if some price is in both."""
    lo_a, hi_a = a_min if a_min is not None else Decimal("-1"), a_max
    lo_b, hi_b = b_min if b_min is not None else Decimal("-1"), b_max
    return (hi_b is None or lo_a < hi_b) and (hi_a is None or lo_b < hi_a)


def _name_routes(path: str, model: type[Brand] | type[Category], label: str) -> None:
    entity = label.lower()

    @router.get(f"/{path}", response_model=list[NameOut], name=f"list_{path}")
    def list_items(
        ctx: AuthContext = Depends(require_permission("product:read")),
        db: Session = Depends(get_db),
    ) -> Any:
        return db.scalars(
            select(model).where(model.business_id == ctx.business_id).order_by(model.name)
        ).all()

    @router.post(
        f"/{path}",
        response_model=NameOut,
        status_code=status.HTTP_201_CREATED,
        name=f"create_{path}",
    )
    def create_item(
        body: NameIn,
        ctx: AuthContext = Depends(require_permission("product:write")),
        db: Session = Depends(get_db),
    ) -> Any:
        item = model(business_id=ctx.business_id, name=body.name.strip())
        db.add(item)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            raise HTTPException(status.HTTP_409_CONFLICT, f"{label} already exists") from None
        record_audit(
            db,
            business_id=ctx.business_id,
            user_id=ctx.user.id,
            action=f"{entity}.created",
            entity_type=entity,
            entity_id=item.id,
            after={"name": item.name},
        )
        db.commit()
        return item


_name_routes("categories", Category, "Category")
_name_routes("brands", Brand, "Brand")


@router.get("/tax-rates", response_model=list[TaxRateOut])
def list_tax_rates(
    on: date | None = None,
    ctx: AuthContext = Depends(require_permission("product:read")),
    db: Session = Depends(get_db),
) -> Any:
    """All rates, or only those in force on a given date."""
    stmt = select(TaxRate).where(TaxRate.business_id == ctx.business_id)
    if on:
        stmt = stmt.where(
            TaxRate.effective_from <= on,
            (TaxRate.effective_to.is_(None)) | (TaxRate.effective_to >= on),
        )
    return db.scalars(stmt.order_by(TaxRate.name, TaxRate.effective_from)).all()


@router.post("/tax-rates", response_model=TaxRateOut, status_code=status.HTTP_201_CREATED)
def create_tax_rate(
    body: TaxRateIn,
    ctx: AuthContext = Depends(require_permission("product:write")),
    db: Session = Depends(get_db),
) -> Any:
    if body.effective_to and body.effective_to < body.effective_from:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "effective_to is before start")
    lo, hi = body.min_unit_price, body.max_unit_price
    if lo is not None and hi is not None and hi <= lo:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "max price must exceed min price"
        )
    for other in db.scalars(
        select(TaxRate).where(TaxRate.business_id == ctx.business_id, TaxRate.name == body.name)
    ):
        if _windows_overlap(
            body.effective_from, body.effective_to, other.effective_from, other.effective_to
        ) and _slabs_overlap(lo, hi, other.min_unit_price, other.max_unit_price):
            raise HTTPException(
                status.HTTP_409_CONFLICT, "Overlaps an existing rate with the same name"
            )
    rate = TaxRate(business_id=ctx.business_id, **body.model_dump())
    db.add(rate)
    try:
        db.flush()
    except IntegrityError:  # the database's exclusion constraint caught a concurrent overlap
        db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Overlaps an existing rate with the same name"
        ) from None
    record_audit(
        db,
        business_id=ctx.business_id,
        user_id=ctx.user.id,
        action="tax_rate.created",
        entity_type="tax_rate",
        entity_id=rate.id,
        after=TaxRateOut.model_validate(rate).model_dump(mode="json"),
    )
    db.commit()
    return rate


@router.patch("/tax-rates/{rate_id}/end", response_model=TaxRateOut)
def end_tax_rate(
    rate_id: uuid.UUID,
    effective_to: date,
    ctx: AuthContext = Depends(require_permission("product:write")),
    db: Session = Depends(get_db),
) -> Any:
    """Closes a rate's window (e.g. when GST changes). It never edits the rate itself."""
    rate = db.get(TaxRate, rate_id)
    if rate is None or rate.business_id != ctx.business_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tax rate not found")
    if effective_to < rate.effective_from:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "End is before start")
    for other in db.scalars(
        select(TaxRate).where(
            TaxRate.business_id == ctx.business_id,
            TaxRate.name == rate.name,
            TaxRate.id != rate.id,
        )
    ):
        if _windows_overlap(
            rate.effective_from, effective_to, other.effective_from, other.effective_to
        ) and _slabs_overlap(
            rate.min_unit_price, rate.max_unit_price, other.min_unit_price, other.max_unit_price
        ):
            raise HTTPException(
                status.HTTP_409_CONFLICT, "Overlaps an existing rate with the same name"
            )
    before = rate.effective_to
    rate.effective_to = effective_to
    record_audit(
        db,
        business_id=ctx.business_id,
        user_id=ctx.user.id,
        action="tax_rate.ended",
        entity_type="tax_rate",
        entity_id=rate.id,
        before={"effective_to": str(before)},
        after={"effective_to": str(effective_to)},
    )
    db.commit()
    return rate
