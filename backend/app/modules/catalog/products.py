import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, require_permission
from app.db.session import get_db
from app.models import (
    Brand,
    Category,
    Inventory,
    Product,
    ProductImage,
    ProductVariant,
    TaxRate,
)
from app.modules.catalog.schemas import (
    ImageOut,
    ProductIn,
    ProductOut,
    ProductUpdate,
    VariantIn,
    VariantLookup,
    VariantOut,
    VariantUpdate,
)
from app.services.audit import record_audit
from app.services.identifiers import barcode_svg, generate_barcode, generate_sku

router = APIRouter(tags=["products"])


def _variant_out(p: Product, v: ProductVariant) -> VariantOut:
    return VariantOut(
        id=v.id,
        product_id=v.product_id,
        sku=v.sku,
        barcode=v.barcode,
        size=v.size,
        colour=v.colour,
        selling_price=v.selling_price if v.selling_price is not None else p.selling_price,
        cost_price=v.cost_price if v.cost_price is not None else p.cost_price,
        has_price_override=v.selling_price is not None,
        is_active=v.is_active,
    )


def _product_out(db: Session, products: list[Product]) -> list[ProductOut]:
    ids = [p.id for p in products]
    variants = db.scalars(
        select(ProductVariant)
        .where(ProductVariant.product_id.in_(ids))
        .order_by(ProductVariant.size, ProductVariant.colour)
    ).all()
    images = db.scalars(
        select(ProductImage).where(ProductImage.product_id.in_(ids)).order_by(ProductImage.position)
    ).all()
    return [
        ProductOut(
            **{
                f: getattr(p, f)
                for f in (
                    "id",
                    "name",
                    "description",
                    "category_id",
                    "brand_id",
                    "hsn_code",
                    "tax_rate_id",
                    "selling_price",
                    "cost_price",
                    "is_active",
                )  # fmt: skip
            },
            variants=[_variant_out(p, v) for v in variants if v.product_id == p.id],
            images=[
                ImageOut(id=i.id, url=f"/media/{i.file_name}", position=i.position)
                for i in images
                if i.product_id == p.id
            ],
        )
        for p in products
    ]


def _owned(db: Session, model: Any, obj_id: uuid.UUID | None, ctx: AuthContext, label: str) -> None:
    if obj_id is None:
        return
    obj = db.get(model, obj_id)
    if obj is None or obj.business_id != ctx.business_id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Unknown {label}")


def _get_product(db: Session, ctx: AuthContext, product_id: uuid.UUID) -> Product:
    product = db.get(Product, product_id)
    if product is None or product.business_id != ctx.business_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Product not found")
    return product


def _add_variant(db: Session, ctx: AuthContext, product: Product, v: VariantIn) -> ProductVariant:
    variant = ProductVariant(
        business_id=ctx.business_id,
        product_id=product.id,
        sku=v.sku or generate_sku(db, ctx.business_id, product.name, v.size, v.colour),
        barcode=v.barcode or generate_barcode(db, ctx.business_id),
        size=v.size.strip(),
        colour=v.colour.strip(),
        selling_price=v.selling_price,
        cost_price=v.cost_price,
    )
    db.add(variant)
    db.flush()
    return variant


def _conflict(db: Session) -> HTTPException:
    db.rollback()
    return HTTPException(
        status.HTTP_409_CONFLICT, "SKU, barcode or size/colour combination already exists"
    )


@router.get("/products", response_model=list[ProductOut])
def list_products(
    q: str | None = None,
    category_id: uuid.UUID | None = None,
    include_inactive: bool = False,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    ctx: AuthContext = Depends(require_permission("product:read")),
    db: Session = Depends(get_db),
) -> list[ProductOut]:
    stmt = select(Product).where(Product.business_id == ctx.business_id)
    if not include_inactive:
        stmt = stmt.where(Product.is_active.is_(True))
    if category_id:
        stmt = stmt.where(Product.category_id == category_id)
    if q:
        like = f"%{q}%"
        match_variant = select(ProductVariant.product_id).where(
            or_(ProductVariant.sku.ilike(like), ProductVariant.barcode == q)
        )
        stmt = stmt.where(or_(Product.name.ilike(like), Product.id.in_(match_variant)))
    products = list(db.scalars(stmt.order_by(Product.name).limit(limit).offset(offset)))
    return _product_out(db, products)


@router.post("/products", response_model=ProductOut, status_code=status.HTTP_201_CREATED)
def create_product(
    body: ProductIn,
    ctx: AuthContext = Depends(require_permission("product:write")),
    db: Session = Depends(get_db),
) -> ProductOut:
    _owned(db, Category, body.category_id, ctx, "category")
    _owned(db, Brand, body.brand_id, ctx, "brand")
    _owned(db, TaxRate, body.tax_rate_id, ctx, "tax rate")
    product = Product(business_id=ctx.business_id, **body.model_dump(exclude={"variants"}))
    db.add(product)
    db.flush()
    try:
        for v in body.variants:
            _add_variant(db, ctx, product, v)
    except IntegrityError:
        raise _conflict(db) from None
    record_audit(
        db,
        business_id=ctx.business_id,
        user_id=ctx.user.id,
        action="product.created",
        entity_type="product",
        entity_id=product.id,
        after={"name": product.name, "variants": len(body.variants)},
    )
    db.commit()
    return _product_out(db, [product])[0]


@router.get("/products/{product_id}", response_model=ProductOut)
def get_product(
    product_id: uuid.UUID,
    ctx: AuthContext = Depends(require_permission("product:read")),
    db: Session = Depends(get_db),
) -> ProductOut:
    return _product_out(db, [_get_product(db, ctx, product_id)])[0]


@router.patch("/products/{product_id}", response_model=ProductOut)
def update_product(
    product_id: uuid.UUID,
    body: ProductUpdate,
    ctx: AuthContext = Depends(require_permission("product:write")),
    db: Session = Depends(get_db),
) -> ProductOut:
    product = _get_product(db, ctx, product_id)
    changes = body.model_dump(exclude_unset=True)
    _owned(db, Category, changes.get("category_id"), ctx, "category")
    _owned(db, Brand, changes.get("brand_id"), ctx, "brand")
    _owned(db, TaxRate, changes.get("tax_rate_id"), ctx, "tax rate")
    before = {k: str(getattr(product, k)) for k in changes}
    for field, value in changes.items():
        setattr(product, field, value)
    record_audit(
        db,
        business_id=ctx.business_id,
        user_id=ctx.user.id,
        action="product.updated",
        entity_type="product",
        entity_id=product.id,
        before=before,
        after={k: str(v) for k, v in changes.items()},
    )
    db.commit()
    return _product_out(db, [product])[0]


@router.post(
    "/products/{product_id}/variants",
    response_model=VariantOut,
    status_code=status.HTTP_201_CREATED,
)
def add_variant(
    product_id: uuid.UUID,
    body: VariantIn,
    ctx: AuthContext = Depends(require_permission("product:write")),
    db: Session = Depends(get_db),
) -> VariantOut:
    product = _get_product(db, ctx, product_id)
    try:
        variant = _add_variant(db, ctx, product, body)
    except IntegrityError:
        raise _conflict(db) from None
    record_audit(
        db,
        business_id=ctx.business_id,
        user_id=ctx.user.id,
        action="variant.created",
        entity_type="variant",
        entity_id=variant.id,
        after={"sku": variant.sku, "size": variant.size, "colour": variant.colour},
    )
    db.commit()
    return _variant_out(product, variant)


def _get_variant(db: Session, ctx: AuthContext, variant_id: uuid.UUID) -> ProductVariant:
    variant = db.get(ProductVariant, variant_id)
    if variant is None or variant.business_id != ctx.business_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Variant not found")
    return variant


@router.patch("/variants/{variant_id}", response_model=VariantOut)
def update_variant(
    variant_id: uuid.UUID,
    body: VariantUpdate,
    ctx: AuthContext = Depends(require_permission("product:write")),
    db: Session = Depends(get_db),
) -> VariantOut:
    variant = _get_variant(db, ctx, variant_id)
    changes = body.model_dump(exclude_unset=True)
    before = {k: str(getattr(variant, k)) for k in changes}
    for field, value in changes.items():
        setattr(variant, field, value)
    try:
        db.flush()
    except IntegrityError:
        raise _conflict(db) from None
    record_audit(
        db,
        business_id=ctx.business_id,
        user_id=ctx.user.id,
        action="variant.updated",
        entity_type="variant",
        entity_id=variant.id,
        before=before,
        after={k: str(v) for k, v in changes.items()},
    )
    product = db.get(Product, variant.product_id)
    assert product is not None
    db.commit()
    return _variant_out(product, variant)


@router.get("/variants/lookup", response_model=list[VariantLookup])
def lookup_variants(
    q: str = Query(min_length=1, max_length=64),
    store_id: uuid.UUID | None = None,
    ctx: AuthContext = Depends(require_permission("product:read")),
    db: Session = Depends(get_db),
) -> list[VariantLookup]:
    """POS search: an exact barcode or SKU match wins; otherwise a name/SKU substring match."""
    if store_id:
        ctx.require_store(store_id)
    base = (
        select(ProductVariant, Product)
        .join(Product, Product.id == ProductVariant.product_id)
        .where(
            ProductVariant.business_id == ctx.business_id,
            ProductVariant.is_active.is_(True),
            Product.is_active.is_(True),
        )
    )
    exact = db.execute(
        base.where(or_(ProductVariant.barcode == q, ProductVariant.sku == q.upper()))
    ).all()
    rows = (
        exact
        or db.execute(
            base.where(or_(Product.name.ilike(f"%{q}%"), ProductVariant.sku.ilike(f"%{q}%")))
            .order_by(Product.name)
            .limit(20)
        ).all()
    )
    stock: dict[uuid.UUID, int] = {}
    if store_id and rows:
        stock = {
            i.variant_id: i.quantity
            for i in db.scalars(
                select(Inventory).where(
                    Inventory.store_id == store_id,
                    Inventory.variant_id.in_([v.id for v, _ in rows]),
                )
            )
        }
    return [
        VariantLookup(
            variant_id=v.id,
            product_id=p.id,
            product_name=p.name,
            sku=v.sku,
            barcode=v.barcode,
            size=v.size,
            colour=v.colour,
            selling_price=v.selling_price if v.selling_price is not None else p.selling_price,
            hsn_code=p.hsn_code,
            tax_rate_id=p.tax_rate_id,
            quantity=stock.get(v.id, 0) if store_id else None,
        )
        for v, p in rows
    ]


@router.get("/variants/{variant_id}/barcode.svg")
def variant_barcode(
    variant_id: uuid.UUID,
    ctx: AuthContext = Depends(require_permission("product:read")),
    db: Session = Depends(get_db),
) -> Response:
    variant = _get_variant(db, ctx, variant_id)
    return Response(barcode_svg(variant.barcode), media_type="image/svg+xml")
