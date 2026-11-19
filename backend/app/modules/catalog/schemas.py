import uuid
from datetime import date
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

Price = Annotated[Decimal, Field(ge=0, max_digits=10, decimal_places=2)]
HSN = Annotated[str, Field(pattern=r"^\d{4,8}$")]


class NameIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class NameOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str


class TaxRateIn(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    rate: Annotated[Decimal, Field(ge=0, le=100, max_digits=5, decimal_places=2)]
    effective_from: date
    effective_to: date | None = None


class TaxRateOut(TaxRateIn):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID


class VariantIn(BaseModel):
    size: str = Field(default="", max_length=30)
    colour: str = Field(default="", max_length=30)
    sku: str | None = Field(default=None, min_length=1, max_length=40)
    barcode: str | None = Field(default=None, min_length=1, max_length=32)
    selling_price: Price | None = None
    cost_price: Price | None = None


class VariantUpdate(BaseModel):
    sku: str | None = Field(default=None, min_length=1, max_length=40)
    barcode: str | None = Field(default=None, min_length=1, max_length=32)
    selling_price: Price | None = None
    cost_price: Price | None = None
    is_active: bool | None = None


class VariantOut(BaseModel):
    id: uuid.UUID
    product_id: uuid.UUID
    sku: str
    barcode: str
    size: str
    colour: str
    selling_price: Decimal  # effective price (override, else the product's)
    cost_price: Decimal
    has_price_override: bool
    is_active: bool


class ImageOut(BaseModel):
    id: uuid.UUID
    url: str
    position: int


class ProductIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    category_id: uuid.UUID | None = None
    brand_id: uuid.UUID | None = None
    hsn_code: HSN | None = None
    tax_rate_id: uuid.UUID | None = None
    selling_price: Price
    cost_price: Price = Decimal("0")
    variants: list[VariantIn] = Field(default_factory=lambda: [VariantIn()], max_length=200)


class ProductUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    category_id: uuid.UUID | None = None
    brand_id: uuid.UUID | None = None
    hsn_code: HSN | None = None
    tax_rate_id: uuid.UUID | None = None
    selling_price: Price | None = None
    cost_price: Price | None = None
    is_active: bool | None = None


class ProductOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    category_id: uuid.UUID | None
    brand_id: uuid.UUID | None
    hsn_code: str | None
    tax_rate_id: uuid.UUID | None
    selling_price: Decimal
    cost_price: Decimal
    is_active: bool
    variants: list[VariantOut]
    images: list[ImageOut]


class VariantLookup(BaseModel):
    variant_id: uuid.UUID
    product_id: uuid.UUID
    product_name: str
    sku: str
    barcode: str
    size: str
    colour: str
    selling_price: Decimal
    hsn_code: str | None
    tax_rate_id: uuid.UUID | None
    quantity: int | None  # only when a store is given
