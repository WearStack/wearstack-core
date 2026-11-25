"""Generates shared/offline-vectors.json from the server's own arithmetic (the authority).

The browser re-implements two small rules so a till can work offline: the tax-inclusive total with
rupee rounding, and the "free discount" limit. Both languages are tested against this one file, so
they cannot drift apart. Run:  cd backend && PYTHONPATH=. uv run python ../shared/make_offline_vectors.py
"""

import json
from decimal import Decimal as D
from pathlib import Path

from app.services import gst

TOTALS = [  # each case is a basket: [(unit_price, quantity, discount), ...]
    [("1299.00", 1, "0")],
    [("1299.00", 2, "0")],
    [("999.99", 1, "0")],  # 999.99 -> 1000, round-off +0.01
    [("999.50", 1, "0")],  # exact half rounds up
    [("999.49", 1, "0")],
    [("0.50", 1, "0")],
    [("0.49", 1, "0")],
    [("100.00", 3, "0.50")],
    [("1299.00", 1, "129.90"), ("599.00", 2, "59.80")],
    [("1899.00", 1, "0.01")],
    [("33.33", 3, "0")],  # 99.99
    [("2499.99", 1, "0"), ("0.01", 1, "0")],
    [("10.00", 10000, "0")],
    [("1299.00", 1, "1299.00")],  # fully discounted: zero total
    [("1.15", 7, "0.05"), ("2.35", 3, "0")],
]
LIMITS = [  # (line gross, free-discount percent)
    ("1299.00", 10), ("0.05", 10), ("0.04", 10), ("999.99", 10), ("1.00", 10),
    ("1299.00", 0), ("1299.00", 100), ("33.33", 15), ("0.01", 50), ("12345.67", 7),
]  # fmt: skip


def totals_case(basket: list[tuple[str, int, str]]) -> dict[str, object]:
    sub = D("0")
    for price, qty, disc in basket:
        sub += gst.money(D(price) * qty) - gst.money(D(disc))
    total, off = gst.round_to_rupee(sub)
    return {
        "lines": [{"unit_price": p, "quantity": q, "discount": d} for p, q, d in basket],
        "subtotal": f"{sub:.2f}", "grand_total": f"{total:.2f}", "round_off": f"{off:.2f}",
    }  # fmt: skip


def limit_case(gross: str, pct: int) -> dict[str, object]:
    return {"gross": gross, "percent": pct, "limit": f"{gst.money(D(gross) * pct / 100):.2f}"}


def build() -> dict[str, object]:
    return {
        "totals": [totals_case(b) for b in TOTALS],
        "discount_limits": [limit_case(g, p) for g, p in LIMITS],
    }


# The same file in two places: shared/ (the reference) and next to the browser tests, because the
# frontend is built in its own Docker context and cannot import from outside its folder.
TARGETS = [
    Path(__file__).with_name("offline-vectors.json"),
    Path(__file__).resolve().parents[1] / "frontend" / "src" / "offline" / "offline-vectors.json",
]

if __name__ == "__main__":
    text = json.dumps(build(), indent=2) + "\n"
    for out in TARGETS:
        out.write_text(text)
        print(f"wrote {out}")
