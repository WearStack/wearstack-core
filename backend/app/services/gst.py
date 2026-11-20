"""GST arithmetic. Pure functions over Decimal: no database, no floats, no rates of its own.

Prices are tax-inclusive (Indian retail MRP). For a line whose tax-inclusive amount is G at rate
r%, taxable value = G / (1 + r/100) and tax = G - taxable, so taxable + tax always equals G
exactly. Intra-state tax is split into equal CGST and SGST halves (any odd paisa goes to SGST);
inter-state tax is all IGST.
"""

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

CENT = Decimal("0.01")
RUPEE = Decimal("1")
ZERO = Decimal("0.00")

SlabBasis = Literal["after_discount", "before_discount"]


def money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class LineTax:
    rate: Decimal
    gross: Decimal  # tax-inclusive amount after discount
    taxable: Decimal
    cgst: Decimal
    sgst: Decimal
    igst: Decimal

    @property
    def tax(self) -> Decimal:
        return self.cgst + self.sgst + self.igst


def split_inclusive(gross: Decimal, rate: Decimal, interstate: bool) -> LineTax:
    if gross < 0 or not (Decimal(0) <= rate <= Decimal(100)):
        raise ValueError("gross must be >= 0 and rate within 0..100")
    gross = money(gross)
    taxable = money(gross / (1 + rate / 100))
    tax = gross - taxable
    if interstate:
        return LineTax(rate, gross, taxable, ZERO, ZERO, tax)
    cgst = money(tax / 2)
    return LineTax(rate, gross, taxable, cgst, tax - cgst, ZERO)


def slab_unit_price(
    unit_price: Decimal, quantity: int, discount: Decimal, basis: SlabBasis
) -> Decimal:
    """The per-unit price compared against a rate's price slab. Not rounded, so a slab boundary
    is never crossed by rounding."""
    if quantity <= 0:
        raise ValueError("quantity must be positive")
    if discount < 0 or discount > unit_price * quantity:
        raise ValueError("discount must be between 0 and the line amount")
    if basis == "before_discount":
        return unit_price
    return (unit_price * quantity - discount) / quantity


def round_to_rupee(amount: Decimal) -> tuple[Decimal, Decimal]:
    """Returns (rounded total, round_off) with rounded = amount + round_off."""
    rounded = amount.quantize(RUPEE, rounding=ROUND_HALF_UP).quantize(CENT)
    return rounded, rounded - amount


def financial_year(on: date) -> str:
    """Indian financial year runs April to March, e.g. 2026-27."""
    start = on.year if on.month >= 4 else on.year - 1
    return f"{start}-{(start + 1) % 100:02d}"
