import uuid
from datetime import date, datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, require_permission
from app.db.session import get_db
from app.models import Store
from app.services import reports as svc
from app.services.report_export import report_csv, report_pdf

router = APIRouter(prefix="/reports", tags=["reports"])
Name = Literal["sales", "gst", "top-products", "stock", "purchases"]


class ColumnOut(BaseModel):
    key: str
    label: str
    kind: str


class ReportOut(BaseModel):
    title: str
    columns: list[ColumnOut]
    rows: list[dict[str, Any]]
    totals: dict[str, Any] | None
    meta: dict[str, Any]
    start: date | None = None
    end: date | None = None


class Params:
    """Shared query parameters. Each report reads the ones it needs and ignores the rest."""

    def __init__(
        self,
        start: date | None = Query(default=None, alias="from"),
        end: date | None = Query(default=None, alias="to"),
        store_id: uuid.UUID | None = None,
        group: svc.Group = "day",
        rank: Literal["quantity", "revenue"] = "quantity",
        limit: int = Query(10, ge=1, le=100),
        breakdown: Literal["period", "supplier"] = "period",
        low_only: bool = False,
        hide_zero: bool = False,
    ) -> None:
        today = datetime.now(svc.IST).date()
        self.end = end or today
        self.start = start or (self.end - timedelta(days=29))
        self.store_id, self.group, self.rank, self.limit = store_id, group, rank, limit
        self.breakdown, self.low_only, self.hide_zero = breakdown, low_only, hide_zero


def _stores(ctx: AuthContext, store_id: uuid.UUID | None) -> set[uuid.UUID]:
    if store_id is None:
        return set(ctx.store_ids)
    ctx.require_store(store_id)
    return {store_id}


def _build(name: Name, db: Session, ctx: AuthContext, p: Params) -> svc.Report:
    stores = _stores(ctx, p.store_id)
    biz = ctx.business_id
    try:
        if name == "sales":
            return svc.sales_summary(db, biz, stores, p.start, p.end, p.group)
        if name == "gst":
            return svc.gst_summary(db, biz, stores, p.start, p.end)
        if name == "top-products":
            return svc.top_products(db, biz, stores, p.start, p.end, p.rank, p.limit)
        if name == "purchases":
            return svc.purchases_summary(db, biz, stores, p.start, p.end, p.group, p.breakdown)
        return svc.stock_report(db, biz, stores, p.low_only, p.hide_zero)
    except svc.ReportError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from None


def _subtitle(db: Session, ctx: AuthContext, name: Name, p: Params) -> str:
    names = db.scalars(
        select(Store.name).where(Store.id.in_(_stores(ctx, p.store_id))).order_by(Store.name)
    ).all()
    where = ", ".join(names) or "no stores"
    if name == "stock":
        return f"Stock as of now · {where}"
    return f"{p.start.isoformat()} to {p.end.isoformat()} · {where}"


@router.get("/overview")
def overview(
    range: svc.Range = "today",  # noqa: A002 - the query parameter is called "range"
    store_id: uuid.UUID | None = None,
    ctx: AuthContext = Depends(require_permission("report:read")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return svc.overview(db, ctx.business_id, _stores(ctx, store_id), range)


@router.get("/{name}.csv")
def export_csv(
    name: Name,
    p: Params = Depends(),
    ctx: AuthContext = Depends(require_permission("report:read")),
    db: Session = Depends(get_db),
) -> Response:
    report = _build(name, db, ctx, p)
    body = report_csv(report, _subtitle(db, ctx, name, p))
    return Response(body, media_type="text/csv; charset=utf-8", headers=_attachment(name, p, "csv"))


@router.get("/{name}.pdf")
def export_pdf(
    name: Name,
    p: Params = Depends(),
    ctx: AuthContext = Depends(require_permission("report:read")),
    db: Session = Depends(get_db),
) -> Response:
    report = _build(name, db, ctx, p)
    body = report_pdf(report, _subtitle(db, ctx, name, p))
    return Response(body, media_type="application/pdf", headers=_attachment(name, p, "pdf"))


@router.get("/{name}", response_model=ReportOut)
def get_report(
    name: Name,
    p: Params = Depends(),
    ctx: AuthContext = Depends(require_permission("report:read")),
    db: Session = Depends(get_db),
) -> ReportOut:
    r = _build(name, db, ctx, p)
    return ReportOut(
        title=r.title,
        columns=[ColumnOut(key=c.key, label=c.label, kind=c.kind) for c in r.columns],
        rows=r.rows,
        totals=r.totals,
        meta=r.meta,
        start=None if name == "stock" else p.start,
        end=None if name == "stock" else p.end,
    )


def _attachment(name: Name, p: Params, ext: str) -> dict[str, str]:
    span = "" if name == "stock" else f"-{p.start.isoformat()}_to_{p.end.isoformat()}"
    return {"Content-Disposition": f'attachment; filename="{name}{span}.{ext}"'}
