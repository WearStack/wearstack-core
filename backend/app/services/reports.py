"""Read-only business reports. Every report is a `Report`: typed columns plus rows, so the JSON
API, the UI tables, CSV and PDF all render from the same data and cannot disagree.

Dates are Indian dates (Asia/Kolkata) and weeks start on Monday. Returns arrive in a later
phase; until then these reports count sales only."""

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any, Literal
from zoneinfo import ZoneInfo

from sqlalchemy import Date, case, cast, func, select
from sqlalchemy.orm import Session

from app.models import (
    Inventory,
    Payment,
    Product,
    ProductVariant,
    Purchase,
    Sale,
    SaleItem,
    Store,
    Supplier,
)

IST = ZoneInfo("Asia/Kolkata")
MAX_RANGE_DAYS = 400
Group = Literal["day", "week", "month"]
ZERO = Decimal("0.00")


class ReportError(ValueError):
    pass


@dataclass
class Column:
    key: str
    label: str
    kind: Literal["text", "int", "money", "percent"] = "text"


@dataclass
class Report:
    title: str
    columns: list[Column]
    rows: list[dict[str, Any]]
    totals: dict[str, Any] | None = None
    meta: dict[str, Any] = field(default_factory=dict)


def money(value: Any) -> str:
    return f"{Decimal(value or 0).quantize(Decimal('0.01')):.2f}"


def bounds(start: date, end: date) -> tuple[datetime, datetime]:
    """[start 00:00, end+1 00:00) in Indian time."""
    if end < start:
        raise ReportError("The end date is before the start date")
    if (end - start).days > MAX_RANGE_DAYS:
        raise ReportError(f"Choose a range of at most {MAX_RANGE_DAYS} days")
    return (
        datetime.combine(start, time.min, tzinfo=IST),
        datetime.combine(end + timedelta(days=1), time.min, tzinfo=IST),
    )


def bucket_starts(start: date, end: date, group: Group) -> list[date]:
    """Every period start between start and end, so empty periods show as zero, not as gaps."""
    if group == "day":
        first = start
    elif group == "week":
        first = start - timedelta(days=start.weekday())
    else:
        first = start.replace(day=1)
    out, cur = [], first
    while cur <= end:
        out.append(cur)
        if group == "day":
            cur += timedelta(days=1)
        elif group == "week":
            cur += timedelta(days=7)
        else:
            cur = (cur.replace(day=28) + timedelta(days=4)).replace(day=1)
    return out


def _label(d: date, group: Group) -> str:
    if group == "month":
        return d.strftime("%Y-%m")
    return d.isoformat() if group == "day" else f"Week of {d.isoformat()}"


def _bucket(group: Group, ts: Any) -> Any:
    return cast(func.date_trunc(group, func.timezone("Asia/Kolkata", ts)), Date)


def _sum(col: Any) -> Any:
    return func.coalesce(func.sum(col), 0)


def sales_summary(
    db: Session,
    business_id: uuid.UUID,
    store_ids: set[uuid.UUID],
    start: date,
    end: date,
    group: Group,
) -> Report:
    lo, hi = bounds(start, end)
    where = (
        Sale.business_id == business_id, Sale.store_id.in_(store_ids),
        Sale.sold_at >= lo, Sale.sold_at < hi,
    )  # fmt: skip
    b = _bucket(group, Sale.sold_at)
    sales = {
        r[0]: r[1:]
        for r in db.execute(
            select(
                b,
                func.count(Sale.id),
                _sum(Sale.discount_total),
                _sum(Sale.taxable_total),
                _sum(Sale.cgst_total + Sale.sgst_total + Sale.igst_total),
                _sum(Sale.grand_total),
            )
            .where(*where)
            .group_by(b)
        )  # fmt: skip
    }
    bi = _bucket(group, Sale.sold_at)
    lines = {
        r[0]: r[1:]
        for r in db.execute(
            select(
                bi,
                _sum(SaleItem.quantity),
                _sum(SaleItem.unit_cost * SaleItem.quantity),
                func.count(case((SaleItem.unit_cost == 0, 1))),
            )
            .join(Sale, Sale.id == SaleItem.sale_id)
            .where(*where)
            .group_by(bi)
        )  # fmt: skip
    }
    pay = db.execute(
        select(Payment.method, _sum(Payment.amount))
        .join(Sale, Sale.id == Payment.sale_id)
        .where(*where, Payment.status == "confirmed")
        .group_by(Payment.method)
    ).all()

    rows: list[dict[str, Any]] = []
    t = {k: Decimal(0) for k in ("disc", "taxable", "tax", "total", "cost")}
    t_orders = t_items = t_nocost = 0
    for d in bucket_starts(start, end, group):
        orders, disc, taxable, tax, total = sales.get(d, (0, 0, 0, 0, 0))
        items, cost, nocost = lines.get(d, (0, 0, 0))
        margin = Decimal(taxable) - Decimal(cost)
        rows.append({
            "period": _label(d, group), "orders": orders, "items": int(items),
            "discount": money(disc), "taxable": money(taxable), "gst": money(tax),
            "total": money(total), "cost": money(cost), "margin": money(margin),
        })  # fmt: skip
        t_orders += orders
        t_items += int(items)
        t_nocost += nocost
        for k, v in (
            ("disc", disc),
            ("taxable", taxable),
            ("tax", tax),
            ("total", total),
            ("cost", cost),
        ):
            t[k] += Decimal(v)
    margin_total = t["taxable"] - t["cost"]
    return Report(
        title="Sales summary",
        columns=[
            Column("period", "Period"),
            Column("orders", "Orders", "int"),
            Column("items", "Items sold", "int"),
            Column("discount", "Discounts", "money"),
            Column("taxable", "Taxable sales", "money"),
            Column("gst", "GST collected", "money"),
            Column("total", "Total billed", "money"),
            Column("cost", "Cost of goods", "money"),
            Column("margin", "Gross margin", "money"),
        ],  # fmt: skip
        rows=rows,
        totals={
            "period": "Total",
            "orders": t_orders,
            "items": t_items,
            "discount": money(t["disc"]),
            "taxable": money(t["taxable"]),
            "gst": money(t["tax"]),
            "total": money(t["total"]),
            "cost": money(t["cost"]),
            "margin": money(margin_total),
        },  # fmt: skip
        meta={
            "average_order_value": money(t["total"] / t_orders) if t_orders else money(0),
            "margin_percent": f"{(margin_total / t['taxable'] * 100):.1f}"
            if t["taxable"]
            else "0.0",
            "payments": {m: money(a) for m, a in pay},
            # Lines sold with no cost recorded make margin look better than it is.
            "lines_without_cost": t_nocost,
            "note": "Gross margin = taxable sales minus cost of goods. "
            "Expenses and returns are not included.",
        },
    )


def gst_summary(
    db: Session, business_id: uuid.UUID, store_ids: set[uuid.UUID], start: date, end: date
) -> Report:
    lo, hi = bounds(start, end)
    q = (
        select(
            SaleItem.tax_rate, func.count(SaleItem.id), _sum(SaleItem.taxable_value),
            _sum(SaleItem.cgst), _sum(SaleItem.sgst), _sum(SaleItem.igst),
            _sum(SaleItem.line_total),
        )
        .join(Sale, Sale.id == SaleItem.sale_id)
        .where(Sale.business_id == business_id, Sale.store_id.in_(store_ids),
               Sale.sold_at >= lo, Sale.sold_at < hi)
        .group_by(SaleItem.tax_rate).order_by(SaleItem.tax_rate)
    )  # fmt: skip
    rows, tot = [], [Decimal(0)] * 5
    n = 0
    for rate, cnt, taxable, cgst, sgst, igst, total in db.execute(q):
        rows.append({
            "rate": f"{Decimal(rate):.2f}", "lines": cnt, "taxable": money(taxable),
            "cgst": money(cgst), "sgst": money(sgst), "igst": money(igst), "total": money(total),
        })  # fmt: skip
        n += cnt
        for i, v in enumerate((taxable, cgst, sgst, igst, total)):
            tot[i] += Decimal(v)
    return Report(
        title="GST summary by rate",
        columns=[
            Column("rate", "GST rate %", "percent"),
            Column("lines", "Lines", "int"),
            Column("taxable", "Taxable value", "money"),
            Column("cgst", "CGST", "money"),
            Column("sgst", "SGST", "money"),
            Column("igst", "IGST", "money"),
            Column("total", "Invoice value", "money"),
        ],  # fmt: skip
        rows=rows,
        totals={
            "rate": "Total",
            "lines": n,
            "taxable": money(tot[0]),
            "cgst": money(tot[1]),
            "sgst": money(tot[2]),
            "igst": money(tot[3]),
            "total": money(tot[4]),
        },  # fmt: skip
        meta={
            "note": "Outward supplies from POS sales. Review with your accountant before filing."
        },
    )


def top_products(
    db: Session,
    business_id: uuid.UUID,
    store_ids: set[uuid.UUID],
    start: date,
    end: date,
    by: Literal["quantity", "revenue"],
    limit: int,
) -> Report:
    lo, hi = bounds(start, end)
    qty, rev = _sum(SaleItem.quantity), _sum(SaleItem.line_total)
    q = (
        select(ProductVariant.product_id, func.max(SaleItem.product_name), qty, rev,
               _sum(SaleItem.taxable_value - SaleItem.unit_cost * SaleItem.quantity))
        .join(Sale, Sale.id == SaleItem.sale_id)
        .join(ProductVariant, ProductVariant.id == SaleItem.variant_id)
        .where(Sale.business_id == business_id, Sale.store_id.in_(store_ids),
               Sale.sold_at >= lo, Sale.sold_at < hi)
        .group_by(ProductVariant.product_id)
        .order_by((qty if by == "quantity" else rev).desc(), func.max(SaleItem.product_name))
        .limit(limit)
    )  # fmt: skip
    rows = [
        {"rank": i, "product": name, "quantity": int(q_), "revenue": money(r), "margin": money(m)}
        for i, (_, name, q_, r, m) in enumerate(db.execute(q), 1)
    ]
    return Report(
        title="Top products",
        columns=[
            Column("rank", "#", "int"),
            Column("product", "Product"),
            Column("quantity", "Units sold", "int"),
            Column("revenue", "Revenue (incl. GST)", "money"),
            Column("margin", "Gross margin", "money"),
        ],  # fmt: skip
        rows=rows,
    )


def stock_report(
    db: Session, business_id: uuid.UUID, store_ids: set[uuid.UUID], low_only: bool, hide_zero: bool
) -> Report:
    qty = func.coalesce(Inventory.quantity, 0)
    reorder = func.coalesce(Inventory.reorder_level, 0)
    cost = func.coalesce(ProductVariant.cost_price, Product.cost_price)
    price = func.coalesce(ProductVariant.selling_price, Product.selling_price)
    q = (
        select(Store.name, Product.name, ProductVariant.size, ProductVariant.colour,
               ProductVariant.sku, qty, reorder, cost, price)
        .select_from(Store)
        .join(ProductVariant, ProductVariant.business_id == Store.business_id)
        .join(Product, Product.id == ProductVariant.product_id)
        .outerjoin(Inventory, (Inventory.variant_id == ProductVariant.id)
                   & (Inventory.store_id == Store.id))
        .where(Store.business_id == business_id, Store.id.in_(store_ids),
               ProductVariant.is_active.is_(True), Product.is_active.is_(True))
        .order_by(Store.name, Product.name, ProductVariant.size, ProductVariant.colour)
    )  # fmt: skip
    if low_only:  # same rule as the inventory screen: a reorder level is set and has been reached
        q = q.where(reorder > 0, qty <= reorder)
    if hide_zero:
        q = q.where(qty > 0)
    rows, units, at_cost, at_price, low = [], 0, Decimal(0), Decimal(0), 0
    for store, product, size, colour, sku, n, level, c, p in db.execute(q):
        is_low = level > 0 and n <= level
        low += is_low
        units += n
        at_cost += Decimal(c) * n
        at_price += Decimal(p) * n
        rows.append({
            "store": store, "product": product,
            "variant": " / ".join(x for x in (size, colour) if x) or "Default",
            "sku": sku, "quantity": n, "reorder": level,
            "status": "Out" if n == 0 else ("Low" if is_low else "OK"),
            "cost_value": money(Decimal(c) * n), "retail_value": money(Decimal(p) * n),
        })  # fmt: skip
    return Report(
        title="Stock on hand",
        columns=[
            Column("store", "Store"),
            Column("product", "Product"),
            Column("variant", "Variant"),
            Column("sku", "SKU"),
            Column("quantity", "On hand", "int"),
            Column("reorder", "Reorder level", "int"),
            Column("status", "Status"),
            Column("cost_value", "Value at cost", "money"),
            Column("retail_value", "Value at selling price", "money"),
        ],  # fmt: skip
        rows=rows,
        totals={
            "store": "Total",
            "quantity": units,
            "cost_value": money(at_cost),
            "retail_value": money(at_price),
        },  # fmt: skip
        meta={"low_stock_lines": low},
    )


def purchases_summary(
    db: Session,
    business_id: uuid.UUID,
    store_ids: set[uuid.UUID],
    start: date,
    end: date,
    group: Group,
    by: Literal["period", "supplier"],
) -> Report:
    bounds(start, end)  # validates the range
    where = (
        Purchase.business_id == business_id, Purchase.store_id.in_(store_ids),
        Purchase.status == "received", Purchase.bill_date >= start, Purchase.bill_date <= end,
    )  # fmt: skip
    if by == "supplier":
        q = (
            select(Supplier.name, func.count(Purchase.id), _sum(Purchase.total))
            .join(Supplier, Supplier.id == Purchase.supplier_id)
            .where(*where)
            .group_by(Supplier.name)
            .order_by(_sum(Purchase.total).desc())
        )
        rows = [{"label": n, "bills": c, "total": money(t)} for n, c, t in db.execute(q)]
        first = Column("label", "Supplier")
    else:
        b = cast(func.date_trunc(group, Purchase.bill_date), Date)
        found = {
            d: (c, t)
            for d, c, t in db.execute(
                select(b, func.count(Purchase.id), _sum(Purchase.total)).where(*where).group_by(b)
            )
        }
        rows = []
        for d in bucket_starts(start, end, group):
            bills, total = found.get(d, (0, 0))
            rows.append({"label": _label(d, group), "bills": bills, "total": money(total)})
        first = Column("label", "Period")
    return Report(
        title="Purchases summary",
        columns=[
            first,
            Column("bills", "Bills", "int"),
            Column("total", "Purchase value", "money"),
        ],
        rows=rows,
        totals={
            "label": "Total",
            "bills": sum(r["bills"] for r in rows),
            "total": money(sum(Decimal(r["total"]) for r in rows)),
        },  # fmt: skip
        meta={"note": "Received bills only, by supplier bill date."},
    )


Range = Literal["today", "week", "month"]


def period_bounds(rng: Range, today: date) -> tuple[date, date, date, date]:
    """(start, end, previous_start, previous_end). The previous period covers the same number of
    elapsed days, so "this week so far" is compared with "last week over the same days"."""
    if rng == "today":
        start = today
        prev_start = today - timedelta(days=1)
    elif rng == "week":
        start = today - timedelta(days=today.weekday())  # Monday
        prev_start = start - timedelta(days=7)
    else:
        start = today.replace(day=1)
        prev_start = (start - timedelta(days=1)).replace(day=1)
    elapsed = timedelta(days=(today - start).days)
    prev_end = min(prev_start + elapsed, start - timedelta(days=1))
    return start, today, prev_start, prev_end


def _totals(
    db: Session, business_id: uuid.UUID, store_ids: set[uuid.UUID], start: date, end: date
) -> tuple[int, Decimal]:
    lo, hi = bounds(start, end)
    orders, revenue = db.execute(
        select(func.count(Sale.id), _sum(Sale.grand_total)).where(
            Sale.business_id == business_id, Sale.store_id.in_(store_ids),
            Sale.sold_at >= lo, Sale.sold_at < hi,
        )
    ).one()  # fmt: skip
    return int(orders), Decimal(revenue)


def _growth(current: Decimal | int, previous: Decimal | int) -> str | None:
    """Percent change versus the previous period; None when there is nothing to compare with."""
    if not previous:
        return None
    return f"{(Decimal(current) - Decimal(previous)) / Decimal(previous) * 100:.1f}"


def _hour_label(h: int) -> str:
    return f"{h % 12 or 12} {'AM' if h < 12 else 'PM'}"


def _hourly(
    db: Session, business_id: uuid.UUID, store_ids: set[uuid.UUID], day: date
) -> list[dict[str, Any]]:
    lo, hi = bounds(day, day)
    hour = func.extract("hour", func.timezone("Asia/Kolkata", Sale.sold_at))
    found = {
        int(h): Decimal(t)
        for h, t in db.execute(
            select(hour, _sum(Sale.grand_total))
            .where(Sale.business_id == business_id, Sale.store_id.in_(store_ids),
                   Sale.sold_at >= lo, Sale.sold_at < hi)
            .group_by(hour)
        )
    }  # fmt: skip
    # Show the trading day (9 AM to 9 PM), widened if something sold outside it.
    first = min([9, *found]) if found else 9
    last = max([21, *found]) if found else 21
    return [
        {"label": _hour_label(h), "total": money(found.get(h, 0))} for h in range(first, last + 1)
    ]


def overview(
    db: Session, business_id: uuid.UUID, store_ids: set[uuid.UUID], rng: Range = "today"
) -> dict[str, Any]:
    today = datetime.now(IST).date()
    start, end, prev_start, prev_end = period_bounds(rng, today)
    orders, revenue = _totals(db, business_id, store_ids, start, end)
    prev_orders, prev_revenue = _totals(db, business_id, store_ids, prev_start, prev_end)
    if rng == "today":
        kind, points = "hour", _hourly(db, business_id, store_ids, today)
    else:
        daily = sales_summary(db, business_id, store_ids, start, end, "day")
        kind = "day"
        points = [{"label": r["period"], "total": r["total"]} for r in daily.rows]
    low = db.scalar(
        select(func.count()).select_from(Inventory).where(
            Inventory.business_id == business_id, Inventory.store_id.in_(store_ids),
            Inventory.quantity <= Inventory.reorder_level, Inventory.reorder_level > 0,
        )
    )  # fmt: skip
    active = db.scalar(select(func.count()).select_from(Product).where(
        Product.business_id == business_id, Product.is_active.is_(True)))  # fmt: skip
    return {
        "date": today.isoformat(),
        "range": rng,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "orders": orders,
        "revenue": money(revenue),
        "orders_previous": prev_orders,
        "revenue_previous": money(prev_revenue),
        "orders_growth": _growth(orders, prev_orders),
        "revenue_growth": _growth(revenue, prev_revenue),
        "low_stock_items": low or 0,
        "active_products": active or 0,
        "series": {"kind": kind, "points": points},
    }
