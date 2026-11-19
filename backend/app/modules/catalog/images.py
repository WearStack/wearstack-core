import io
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from PIL import Image, UnidentifiedImageError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, require_permission
from app.core.config import get_settings
from app.db.session import get_db
from app.models import Product, ProductImage
from app.modules.catalog.schemas import ImageOut
from app.services.audit import record_audit

router = APIRouter(tags=["products"])

_FORMATS = {
    "JPEG": ("jpg", "image/jpeg"),
    "PNG": ("png", "image/png"),
    "WEBP": ("webp", "image/webp"),
}
MAX_PIXELS = 25_000_000
MAX_IMAGES_PER_PRODUCT = 8


def media_path() -> Path:
    path = Path(get_settings().media_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _product(db: Session, ctx: AuthContext, product_id: uuid.UUID) -> Product:
    product = db.get(Product, product_id)
    if product is None or product.business_id != ctx.business_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Product not found")
    return product


@router.post(
    "/products/{product_id}/images", response_model=ImageOut, status_code=status.HTTP_201_CREATED
)
async def upload_image(
    product_id: uuid.UUID,
    file: UploadFile,
    ctx: AuthContext = Depends(require_permission("product:write")),
    db: Session = Depends(get_db),
) -> ImageOut:
    product = _product(db, ctx, product_id)
    limit = get_settings().max_image_bytes
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "Image is too large")
    # Trust the bytes, not the client-supplied filename or content type.
    try:
        with Image.open(io.BytesIO(data)) as img:
            fmt = img.format or ""
            if img.width * img.height > MAX_PIXELS:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Image is too large")
            img.verify()
    except (UnidentifiedImageError, OSError):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Not a valid image") from None
    if fmt not in _FORMATS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Use a JPEG, PNG or WebP image")
    count = db.scalar(
        select(func.count()).select_from(ProductImage).where(ProductImage.product_id == product.id)
    )
    if (count or 0) >= MAX_IMAGES_PER_PRODUCT:
        raise HTTPException(status.HTTP_409_CONFLICT, "Image limit reached for this product")
    ext, content_type = _FORMATS[fmt]
    name = f"{uuid.uuid4().hex}.{ext}"
    (media_path() / name).write_bytes(data)
    image = ProductImage(
        business_id=ctx.business_id,
        product_id=product.id,
        file_name=name,
        content_type=content_type,
        position=count or 0,
    )
    db.add(image)
    db.flush()
    record_audit(
        db,
        business_id=ctx.business_id,
        user_id=ctx.user.id,
        action="product.image_added",
        entity_type="product",
        entity_id=product.id,
        after={"image_id": str(image.id)},
    )
    db.commit()
    return ImageOut(id=image.id, url=f"/media/{name}", position=image.position)


@router.delete("/products/{product_id}/images/{image_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_image(
    product_id: uuid.UUID,
    image_id: uuid.UUID,
    ctx: AuthContext = Depends(require_permission("product:write")),
    db: Session = Depends(get_db),
) -> None:
    _product(db, ctx, product_id)
    image = db.get(ProductImage, image_id)
    if image is None or image.product_id != product_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Image not found")
    (media_path() / image.file_name).unlink(missing_ok=True)
    db.delete(image)
    record_audit(
        db,
        business_id=ctx.business_id,
        user_id=ctx.user.id,
        action="product.image_removed",
        entity_type="product",
        entity_id=product_id,
        before={"image_id": str(image_id)},
    )
    db.commit()
