"""Fills an EMPTY development database with a demo shop, so the app and its reports can be
explored with realistic data:  uv run python -m app.seed_demo

It refuses to run unless ENVIRONMENT=development and no business exists yet. Sales go through
the real sale code path (with a back-dated clock), so invoices, stock and the ledger are as
consistent as in real use. The GST rates created here are labelled DEMO and are not real rates.
"""

import random
import sys
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from barcode import get as get_barcode
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import AuthContext
from app.core.config import get_settings
from app.core.security import hash_password
from app.db.session import SessionLocal
from app.models import (
    Brand,
    Business,
    Category,
    Customer,
    Inventory,
    Product,
    ProductVariant,
    Purchase,
    PurchaseItem,
    Store,
    Supplier,
    TaxRate,
    User,
    UserStoreAccess,
)
from app.modules.sales.schemas import PaymentIn, SaleIn, SaleLineIn
from app.services.inventory import apply_movement
from app.services.rbac import create_default_roles, permission_codes
from app.services.sales import SaleError, create_sale, price_sale

IST = ZoneInfo("Asia/Kolkata")
PASSWORD = "demo-password-123"
DAYS = 45
CATALOGUE = [  # name, category, brand, price, sizes, colours
    ("Classic Cotton Shirt", "Shirts", "Wear Basics", "1299.00", ["S", "M", "L", "XL"], ["White", "Blue"]),
    ("Linen Casual Shirt", "Shirts", "Urban Fit", "1599.00", ["M", "L", "XL"], ["Beige", "Olive"]),
    ("Slim Fit Denim", "Jeans", "Urban Fit", "1899.00", ["30", "32", "34"], ["Black", "Indigo"]),
    ("Straight Fit Jeans", "Jeans", "Wear Basics", "1499.00", ["30", "32", "34", "36"], ["Blue"]),
    ("Premium Polo T-shirt", "T-Shirts", "Wear Basics", "899.00", ["S", "M", "L", "XL"], ["Orange", "Navy"]),
    ("Graphic Tee", "T-Shirts", "Urban Fit", "599.00", ["S", "M", "L"], ["Black", "White"]),
    ("Classic Chinos", "Trousers", "Wear Basics", "1499.00", ["30", "32", "34"], ["Beige", "Khaki"]),
    ("Formal Trousers", "Trousers", "Urban Fit", "2199.00", ["30", "32", "34", "36"], ["Grey"]),
]  # fmt: skip


def seed(db: Session) -> dict[str, str]:
    rng = random.Random(7)  # fixed seed: the same demo every time
    now = datetime.now(IST)

    biz = Business(name="Demo Clothing Co", state_code="27", gstin="27AAPFU0939F1ZV")
    db.add(biz)
    db.flush()
    roles = create_default_roles(db, biz.id)
    stores = [
        Store(business_id=biz.id, code="MAIN", name="Main Store", state_code="27",
              gstin="27AAPFU0939F1ZV", address="MG Road, Pune", created_at=now - timedelta(days=90)),
        Store(business_id=biz.id, code="BR1", name="Branch Store", state_code="27",
              gstin="27AAPFU0939F1ZV", address="FC Road, Pune", created_at=now - timedelta(days=45)),
    ]  # fmt: skip
    db.add_all(stores)
    db.flush()
    users: dict[str, User] = {}
    for role, email, name in (
        ("Owner", "owner@yopmail.com", "Demo Owner"),
        ("Manager", "manager@yopmail.com", "Demo Manager"),
        ("Cashier", "cashier@yopmail.com", "Demo Cashier"),
    ):
        u = User(business_id=biz.id, role_id=roles[role].id, email=email, full_name=name,
                 password_hash=hash_password(PASSWORD))  # fmt: skip
        db.add(u)
        users[role] = u
    db.flush()
    for u in users.values():
        db.add_all(UserStoreAccess(user_id=u.id, store_id=s.id) for s in stores)

    rate5 = TaxRate(
        business_id=biz.id, name="Demo 5%", rate=Decimal("5"), effective_from=date(2020, 1, 1)
    )
    rate12 = TaxRate(
        business_id=biz.id, name="Demo 12%", rate=Decimal("12"), effective_from=date(2020, 1, 1)
    )
    cats = {
        n: Category(business_id=biz.id, name=n) for n in ("Shirts", "Jeans", "T-Shirts", "Trousers")
    }
    brands = {n: Brand(business_id=biz.id, name=n) for n in ("Wear Basics", "Urban Fit")}
    db.add_all([rate5, rate12, *cats.values(), *brands.values()])
    db.flush()

    owner = users["Owner"]
    owner_role = roles["Owner"]
    ctx = AuthContext(user=owner, role=owner_role, permissions=permission_codes(db, owner_role.id),
                      store_ids={s.id for s in stores})  # fmt: skip

    variants: list[ProductVariant] = []
    for name, cat, brand, price, sizes, colours in CATALOGUE:
        p = Product(
            business_id=biz.id, name=name, category_id=cats[cat].id, brand_id=brands[brand].id,
            hsn_code="6205" if "Shirt" in name else "6203", selling_price=Decimal(price),
            cost_price=(Decimal(price) * Decimal("0.55")).quantize(Decimal("0.01")),
            tax_rate_id=(rate5 if Decimal(price) <= 1000 else rate12).id,
        )  # fmt: skip
        db.add(p)
        db.flush()
        for size in sizes:
            for colour in colours:
                code = f"{abs(hash((name, size, colour))) % 10**11:011d}"
                v = ProductVariant(
                    business_id=biz.id, product_id=p.id, size=size, colour=colour,
                    sku=f"{name[:3].upper()}-{size}-{colour[:3].upper()}",
                    barcode=get_barcode("ean13", "2" + code).get_fullcode(),
                )  # fmt: skip
                db.add(v)
                variants.append(v)
    db.flush()
    for s in stores:
        for v in variants:
            apply_movement(db, business_id=biz.id, store_id=s.id, variant_id=v.id,
                           movement_type="opening", delta=rng.randint(40, 70), user_id=owner.id,
                           reason="Opening stock")  # fmt: skip
        for v in rng.sample(variants, 12):  # reorder levels on some variants
            inv = db.get(Inventory, (v.id, s.id))
            assert inv is not None
            inv.reorder_level = 45  # high enough that some end up 'low'
    db.flush()

    # Two suppliers and a few received bills spread over the period.
    sup = [Supplier(business_id=biz.id, name=n) for n in ("Textile Traders", "Urban Garments Ltd")]
    db.add_all(sup)
    db.flush()
    for i, day_offset in enumerate((38, 27, 14, 6)):
        bill_day = (now - timedelta(days=day_offset)).date()
        pur = Purchase(business_id=biz.id, store_id=stores[0].id, supplier_id=sup[i % 2].id,
                       bill_number=f"BILL-{100 + i}", bill_date=bill_day, status="received",
                       created_by=owner.id, received_by=owner.id, received_at=now - timedelta(days=day_offset))  # fmt: skip
        db.add(pur)
        db.flush()
        total = Decimal(0)
        for v in rng.sample(variants, 6):
            qty, cost = (
                rng.randint(10, 25),
                (Decimal(rng.randint(300, 900))).quantize(Decimal("0.01")),
            )
            db.add(PurchaseItem(purchase_id=pur.id, variant_id=v.id, quantity=qty, unit_cost=cost,
                                line_total=qty * cost))  # fmt: skip
            apply_movement(db, business_id=biz.id, store_id=stores[0].id, variant_id=v.id,
                           movement_type="purchase", delta=qty, user_id=owner.id,
                           reference_type="purchase", reference_id=pur.id)  # fmt: skip
            total += qty * cost
        pur.total = total
    db.flush()

    people = [Customer(business_id=biz.id, name=n, phone=f"98{rng.randint(10000000, 99999999)}",
                       state_code="29" if i % 5 == 0 else "27", marketing_consent=i % 2 == 0)
              for i, n in enumerate(("Asha Rao", "Ravi Kumar", "Meera Iyer", "Sanjay Patil",
                                     "Priya Nair", "Vikram Shah", "Neha Gupta", "Arjun Mehta"))]  # fmt: skip
    db.add_all(people)
    db.commit()

    made = 0
    for back in range(DAYS, -1, -1):  # oldest first, so invoice numbers rise with time
        day = (now - timedelta(days=back)).date()
        busy = 7 if day.weekday() >= 5 else 4
        # Sorted by time: invoice numbers are issued in the order of sale.
        times = sorted(
            (rng.randint(10, 20), rng.randint(0, 59)) for _ in range(rng.randint(1, busy + 2))
        )
        for hour, minute in times:
            store = stores[0] if rng.random() < 0.7 else stores[1]
            when = datetime(day.year, day.month, day.day, hour, minute, tzinfo=IST)
            if when > now:
                continue
            picked = rng.sample(variants, rng.randint(1, 3))
            items = [SaleLineIn(variant_id=v.id, quantity=rng.randint(1, 2)) for v in picked]
            body = SaleIn(idempotency_key=uuid.uuid4(), store_id=store.id, items=items,
                          customer_id=rng.choice([None, None, *[c.id for c in people]]), payments=[])  # fmt: skip
            try:
                total = price_sale(db, ctx, body, now=when).grand_total  # writes nothing
                method = rng.choice(["cash", "cash", "upi", "card"])
                body.payments = [PaymentIn(method=method, amount=total, reference=None if method == "cash" else f"DEMO{rng.randint(10**5, 10**6)}")]  # fmt: skip
                create_sale(db, ctx, body, now=when)
                made += 1
            except SaleError:
                db.rollback()  # e.g. out of stock: skip it, like a real counter would

    # A stock-take: a few variants end up out of stock in the main store, as in a real shop.
    for v in rng.sample(variants, 3):
        on_hand = db.scalar(
            select(Inventory.quantity).where(
                Inventory.variant_id == v.id, Inventory.store_id == stores[0].id
            )
        )
        if on_hand:
            apply_movement(
                db, business_id=biz.id, store_id=stores[0].id, variant_id=v.id,
                movement_type="adjustment", delta=-int(on_hand), user_id=owner.id,
                reason="Stock take: damaged / missing",
            )  # fmt: skip
    db.commit()
    return {"sales": str(made), "products": str(len(CATALOGUE)), "variants": str(len(variants))}


def main() -> int:
    settings = get_settings()
    if settings.environment != "development":
        print(f"Refusing to seed: ENVIRONMENT is {settings.environment!r}, not 'development'.")
        return 1
    with SessionLocal() as db:
        if db.scalar(select(func.count()).select_from(Business)):
            print("Refusing to seed: this database already has a business. Use an empty one.")
            return 1
        result = seed(db)
    print(
        f"Seeded {result['sales']} sales, {result['products']} products ({result['variants']} variants)."
    )
    print(f"Log in as owner@yopmail.com, manager@yopmail.com or cashier@yopmail.com / {PASSWORD}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
