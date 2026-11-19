import uuid
from datetime import date
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
    end = body.effective_to or date.max
    for other in db.scalars(
        select(TaxRate).where(TaxRate.business_id == ctx.business_id, TaxRate.name == body.name)
    ):
        if body.effective_from <= (other.effective_to or date.max) and other.effective_from <= end:
            raise HTTPException(
                status.HTTP_409_CONFLICT, "Overlaps an existing rate with the same name"
            )
    rate = TaxRate(business_id=ctx.business_id, **body.model_dump())
    db.add(rate)
    db.flush()
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
        if rate.effective_from <= (other.effective_to or date.max) and (
            other.effective_from <= effective_to
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
