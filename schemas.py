from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime


# ── Company (고객사) ──────────────────────────────────────
class CompanyCreate(BaseModel):
    name: str
    address: Optional[str] = None
    notes: Optional[str] = None


class CompanyResponse(BaseModel):
    id: int
    name: str
    address: Optional[str]
    notes: Optional[str]
    is_active: bool

    class Config:
        from_attributes = True


# ── Item (품목) ──────────────────────────────────────
class ItemCreate(BaseModel):
    name: str


class ItemResponse(BaseModel):
    id: int
    name: str
    is_active: bool

    class Config:
        from_attributes = True


# ── User ──────────────────────────────────────────
class UserBase(BaseModel):
    name: str
    username: str
    role: str


class UserCreate(UserBase):
    password: str


class UserResponse(UserBase):
    id: int
    is_active: bool

    class Config:
        from_attributes = True


# ── Auth ──────────────────────────────────────────
class Token(BaseModel):
    access_token: str
    token_type: str
    user: UserResponse


# ── Delivery ──────────────────────────────────────
class DeliveryCreate(BaseModel):
    company: str
    destination: str
    item_name: str                          # 품목
    quantity: int                           # 수량 (Kg)
    driver_id: int
    vehicle_number: Optional[str] = None
    scheduled_date: str
    delivery_time: str                      # 배송시간
    notes: Optional[str] = None


class DeliveryUpdate(BaseModel):
    status: Optional[str] = None
    loading_complete_time: Optional[str] = None
    departure_time: Optional[str] = None
    complete_time: Optional[str] = None
    complete_memo: Optional[str] = None


class PhotoResponse(BaseModel):
    id: int
    photo_data: str
    filename: Optional[str]
    uploaded_at: datetime

    class Config:
        from_attributes = True


class DeliveryResponse(BaseModel):
    id: int
    company: str
    destination: str
    item_name: str
    quantity: int
    driver_id: int
    vehicle_number: Optional[str]
    scheduled_date: str
    delivery_time: str
    notes: Optional[str]
    status: str
    loading_complete_time: Optional[str]
    departure_time: Optional[str]
    complete_time: Optional[str]
    complete_memo: Optional[str]
    created_at: datetime
    driver_user: Optional[UserResponse] = None
    photos: List[PhotoResponse] = []

    class Config:
        from_attributes = True
