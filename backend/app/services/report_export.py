import csv
import io
from datetime import datetime
from zoneinfo import ZoneInfo

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.services.reports import Report

IST = ZoneInfo("Asia/Kolkata")
NAVY = colors.HexColor("#124b9b")
LINE = colors.HexColor("#dfe7f1")
_FORMULA_STARTS = ("=", "+", "-", "@", "\t", "\r")


def _safe_cell(value: object, kind: str) -> object:
    """Spreadsheets run text that starts with = + - @ as a formula. Product or customer names are
    user input, so text cells are prefixed with an apostrophe to keep them as plain text."""
    if kind == "text" and isinstance(value, str) and value.startswith(_FORMULA_STARTS):
        return "'" + value
    return value


def report_csv(report: Report, subtitle: str) -> bytes:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow([report.title])
    writer.writerow([subtitle])
    writer.writerow([])
    writer.writerow([c.label for c in report.columns])
    for row in report.rows:
        writer.writerow([_safe_cell(row.get(c.key, ""), c.kind) for c in report.columns])
    if report.totals:
        writer.writerow([_safe_cell(report.totals.get(c.key, ""), c.kind) for c in report.columns])
    # The BOM makes Excel read the file as UTF-8, so names with accents or symbols survive.
    return ("﻿" + out.getvalue()).encode("utf-8")


def report_pdf(report: Report, subtitle: str) -> bytes:
    styles = getSampleStyleSheet()
    small = ParagraphStyle("small", parent=styles["Normal"], fontSize=7.5, leading=9)
    head = ParagraphStyle("head", parent=small, textColor=colors.white, fontName="Helvetica-Bold")
    title = ParagraphStyle("t", parent=styles["Title"], fontSize=15, textColor=NAVY, alignment=0)
    wide = len(report.columns) > 6
    page = landscape(A4) if wide else A4
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=page, leftMargin=12 * mm, rightMargin=12 * mm, topMargin=12 * mm,
        bottomMargin=12 * mm, title=report.title,
    )  # fmt: skip
    numeric = {i for i, c in enumerate(report.columns) if c.kind != "text"}

    def cell(value: object, i: int, style: ParagraphStyle = small) -> Paragraph:
        text = "" if value is None else str(value).replace("&", "&amp;").replace("<", "&lt;")
        right = ParagraphStyle("r", parent=style, alignment=2) if i in numeric else style
        return Paragraph(text, right)

    rows = [[cell(c.label, i, head) for i, c in enumerate(report.columns)]]
    for r in report.rows:
        rows.append([cell(r.get(c.key, ""), i) for i, c in enumerate(report.columns)])
    if report.totals:
        bold = ParagraphStyle("b", parent=small, fontName="Helvetica-Bold")
        rows.append(
            [cell(report.totals.get(c.key, ""), i, bold) for i, c in enumerate(report.columns)]
        )
    table = Table(rows, repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("LINEBELOW", (0, 0), (-1, -1), 0.25, LINE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]
    if report.totals:
        style.append(("LINEABOVE", (0, -1), (-1, -1), 0.75, NAVY))
    table.setStyle(TableStyle(style))
    story: list[object] = [
        Paragraph(report.title, title),
        Paragraph(subtitle, small),
        Spacer(1, 4 * mm),
        table,
    ]
    note = report.meta.get("note")
    if note:
        story += [Spacer(1, 4 * mm), Paragraph(str(note), small)]
    story += [
        Spacer(1, 2 * mm),
        Paragraph(f"Generated {datetime.now(IST).strftime('%d %b %Y, %I:%M %p')} IST", small),
    ]
    doc.build(story)
    return buf.getvalue()
