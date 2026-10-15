from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8)


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    role: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserRead


class ProductRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    sku: str
    category: str
    description: str
    price: float
    stock: int
    is_active: bool


class ProductListResponse(BaseModel):
    items: List[ProductRead]
    total: int
    page: int
    page_size: int
    total_pages: int


class CheckoutItem(BaseModel):
    product_id: int
    quantity: int = Field(..., gt=0)


class CheckoutRequest(BaseModel):
    items: List[CheckoutItem]


class CheckoutResponse(BaseModel):
    order_id: int
    transaction_id: int
    status: str
    total_amount: float


class AnalyticsSummary(BaseModel):
    total_sales: float
    user_signups: int
    order_logs: List[dict]
    order_status_summary: List[dict]
    transaction_status_summary: List[dict]


class WebhookPayload(BaseModel):
    event_id: str
    event_type: str
    order_id: int
    amount: float
    currency: str = "USD"


class WebhookResponse(BaseModel):
    status: str
    message: str
    event_id: Optional[str] = None
