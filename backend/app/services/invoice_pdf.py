import io
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.models import GstDocument, Payment, Sale, SaleItem

NAVY = colors.HexColor("#124b9b")
LINE = colors.HexColor("#dfe7f1")


IST = ZoneInfo("Asia/Kolkata")


def invoice_timestamp(moment: datetime) -> str:
    """Invoices carry Indian time, whatever timezone the server happens to run in."""
    return moment.astimezone(IST).strftime("%d %b %Y, %I:%M %p")


def _rs(value: Decimal) -> str:
    # The built-in PDF fonts have no rupee glyph, so amounts are written with "Rs.".
    return f"{value:,.2f}"


def build_invoice_pdf(
    doc: GstDocument, sale: Sale, items: list[SaleItem], payments: list[Payment]
) -> bytes:
    styles = getSampleStyleSheet()
    small = ParagraphStyle("small", parent=styles["Normal"], fontSize=8, leading=10)
    bold = ParagraphStyle("bold", parent=small, fontName="Helvetica-Bold")
    title = ParagraphStyle(
        "title", parent=styles["Title"], fontSize=15, textColor=NAVY, alignment=0, spaceAfter=2
    )
    seller, buyer = doc.seller, doc.buyer
    supply_kind = "Inter-state (IGST)" if sale.is_interstate else "Intra-state (CGST + SGST)"

    buf = io.BytesIO()
    pdf = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=12 * mm,
        rightMargin=12 * mm,
        topMargin=12 * mm,
        bottomMargin=12 * mm,
        title=f"Tax Invoice {doc.number}",
    )
    story: list[object] = [
        Paragraph(seller["business_name"], title),
        Paragraph(
            f"{seller['store_name']} ({seller['store_code']})"
            + (f" &middot; {seller['address']}" if seller.get("address") else "")
            + f"<br/>GSTIN: {seller.get('gstin') or 'Not registered'} &middot; "
            f"State code: {seller['state_code']}",
            small,
        ),
        Spacer(1, 4 * mm),
        Paragraph("TAX INVOICE", bold),
    ]
    meta = Table(
        [
            [
                Paragraph(f"<b>Invoice no:</b> {doc.number}", small),
                Paragraph(
                    f"<b>Date:</b> {invoice_timestamp(sale.sold_at)}",
                    small,
                ),
            ],
            [
                Paragraph(
                    f"<b>Bill to:</b> {buyer['name']}"
                    + (f"<br/>Phone: {buyer['phone']}" if buyer.get("phone") else "")
                    + (f"<br/>GSTIN: {buyer['gstin']}" if buyer.get("gstin") else ""),
                    small,
                ),
                Paragraph(
                    f"<b>Place of supply:</b> {sale.place_of_supply}<br/>{supply_kind}",
                    small,
                ),
            ],
        ],
        colWidths=[95 * mm, 91 * mm],
    )
    meta.setStyle(
        TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("BOX", (0, 0), (-1, -1), 0.5, LINE)])
    )
    story += [meta, Spacer(1, 4 * mm)]

    rows: list[list[object]] = [
        ["#", "Item", "HSN", "Qty", "Price", "Disc", "Taxable", "GST %", "Tax", "Amount"]
    ]
    for n, i in enumerate(items, 1):
        rows.append(
            [
                str(n),
                Paragraph(f"{i.product_name}<br/>{i.variant_label} &middot; {i.sku}", small),
                i.hsn_code or "-",
                str(i.quantity),
                _rs(i.unit_price),
                _rs(i.discount),
                _rs(i.taxable_value),
                f"{i.tax_rate:g}",
                _rs(i.cgst + i.sgst + i.igst),
                _rs(i.line_total),
            ]
        )
    table = Table(
        rows,
        colWidths=[7, 52, 15, 9, 18, 15, 19, 11, 16, 20],
        repeatRows=1,
    )
    table._argW = [w * mm for w in table._argW]
    table.setStyle(
        TableStyle(
            [
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("BACKGROUND", (0, 0), (-1, 0), NAVY),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("ALIGN", (3, 0), (-1, -1), "RIGHT"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LINEBELOW", (0, 0), (-1, -1), 0.25, LINE),
            ]
        )
    )
    story += [table, Spacer(1, 4 * mm)]

    totals = [["Taxable value", _rs(sale.taxable_total)]]
    if sale.is_interstate:
        totals.append(["IGST", _rs(sale.igst_total)])
    else:
        totals += [["CGST", _rs(sale.cgst_total)], ["SGST", _rs(sale.sgst_total)]]
    if sale.discount_total:
        totals.insert(0, ["Discount given", _rs(sale.discount_total)])
    if sale.round_off:
        totals.append(["Round off", _rs(sale.round_off)])
    totals.append(["TOTAL (Rs.)", _rs(sale.grand_total)])
    tt = Table(totals, colWidths=[40 * mm, 30 * mm], hAlign="RIGHT")
    tt.setStyle(
        TableStyle(
            [
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                ("LINEABOVE", (0, -1), (-1, -1), 0.75, NAVY),
            ]
        )
    )
    story += [tt, Spacer(1, 4 * mm)]
    paid = ", ".join(
        f"{p.method.upper()} Rs.{_rs(p.amount)}" + (f" (ref {p.reference})" if p.reference else "")
        for p in payments
    )
    story += [
        Paragraph(f"<b>Payment:</b> {paid or 'None'}", small),
        Spacer(1, 6 * mm),
        Paragraph(
            "Prices include GST. This is a computer-generated invoice. "
            "Goods once sold are subject to the store's return policy.",
            small,
        ),
    ]
    pdf.build(story)
    return buf.getvalue()
