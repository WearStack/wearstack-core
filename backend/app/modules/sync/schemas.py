import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.modules.sales.schemas import PaymentIn

Money = Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=2)]


class DeviceIn(BaseModel):
    identifier: str = Field(min_length=8, max_length=100)  # generated once by the browser
    name: str = Field(min_length=1, max_length=100)
    store_id: uuid.UUID


class DeviceOut(BaseModel):
    id: uuid.UUID
    identifier: str
    name: str
    store_id: uuid.UUID
    is_active: bool
    last_seen_at: datetime | None

    model_config = {"from_attributes": True}


class SyncLineIn(BaseModel):
    variant_id: uuid.UUID
    quantity: int = Field(ge=1, le=10_000)
    unit_price: Money  # what the customer was charged (tax-inclusive)
    discount: Money = Decimal("0")


class SyncSaleIn(BaseModel):
    # Generated on the device when the sale is made; also the sale's idempotency key.
    client_operation_id: uuid.UUID
    store_id: uuid.UUID
    sold_at: datetime  # when it really happened (device clock, checked by the server)
    cashier_id: uuid.UUID
    customer_id: uuid.UUID | None = None
    provisional_number: str | None = Field(default=None, max_length=40)
    items: list[SyncLineIn] = Field(min_length=1, max_length=200)
    payments: list[PaymentIn] = Field(default_factory=list, max_length=10)

    @field_validator("sold_at")
    @classmethod
    def _aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("sold_at must include a timezone")
        return v


class SyncBatchIn(BaseModel):
    device_id: uuid.UUID
    operations: list[SyncSaleIn] = Field(min_length=1)


class SyncResultOut(BaseModel):
    operation_id: uuid.UUID
    client_operation_id: uuid.UUID
    status: Literal["received", "applied", "conflict", "failed", "rejected"]
    sale_id: uuid.UUID | None = None
    invoice_number: str | None = None
    replayed: bool = False
    conflicts: list[dict[str, Any]] = []
    error_code: str | None = None
    error_message: str | None = None


class SyncBatchOut(BaseModel):
    results: list[SyncResultOut]


class OperationLine(BaseModel):
    variant_id: uuid.UUID
    product_name: str
    variant_label: str
    quantity: int
    unit_price: Decimal
    discount: Decimal


class OperationOut(BaseModel):
    id: uuid.UUID
    client_operation_id: uuid.UUID
    provisional_number: str | None
    status: str
    sold_at: datetime
    received_at: datetime
    processed_at: datetime | None
    store_id: uuid.UUID
    device_id: uuid.UUID
    device_name: str | None
    cashier_id: uuid.UUID
    cashier_name: str | None
    total: Decimal
    sale_id: uuid.UUID | None
    invoice_number: str | None
    conflicts: list[dict[str, Any]]
    error_code: str | None
    error_message: str | None
    resolution_note: str | None
    lines: list[OperationLine] = []


class ResolveIn(BaseModel):
    action: Literal["accept", "reject", "retry"]
    note: str | None = Field(default=None, max_length=500)


class CatalogVariant(BaseModel):
    id: uuid.UUID
    product_id: uuid.UUID
    product_name: str
    category: str | None
    size: str
    colour: str
    sku: str
    barcode: str
    price: Decimal
    hsn_code: str | None
    quantity: int
    sellable: bool  # false when it cannot be billed (inactive, or no GST rate in force)


class CatalogCustomer(BaseModel):
    id: uuid.UUID
    name: str
    phone: str | None
    state_code: str | None


class CatalogSettings(BaseModel):
    free_discount_percent: int
    offline_warn_hours: int
    offline_block_hours: int
    offline_max_sale_age_days: int
    sync_batch_max: int


class CatalogOut(BaseModel):
    generated_at: datetime
    store_id: uuid.UUID
    store_name: str
    settings: CatalogSettings
    variants: list[CatalogVariant]
    customers: list[CatalogCustomer]
