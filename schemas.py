from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime


# ── Company (고객사) ──────────────────────────────────────
class CompanyCreate(BaseModel):
    name: str
    address: Optional[str] = None
    contact_name: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    notes: Optional[str] = None


class CompanyUpdate(BaseModel):
    name: Optional[str] = None
    address: Optional[str] = None
    contact_name: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    notes: Optional[str] = None


class CompanyResponse(BaseModel):
    id: int
    name: str
    address: Optional[str]
    contact_name: Optional[str]
    contact_email: Optional[str]
    contact_phone: Optional[str]
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
    department: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    can_create_delivery: bool = False
    can_assign_vehicle: bool = False
    vehicle_id: Optional[int] = None
    vehicle_number: Optional[str] = None
    vehicle_type: Optional[str] = None


class UserCreate(UserBase):
    password: str


class UserUpdate(BaseModel):
    name: Optional[str] = None
    department: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    vehicle_id: Optional[int] = None
    vehicle_number: Optional[str] = None
    vehicle_type: Optional[str] = None


class UserResponse(UserBase):
    id: int
    is_active: bool

    class Config:
        from_attributes = True


class UserPermissionUpdate(BaseModel):
    can_create_delivery: Optional[bool] = None
    can_assign_vehicle: Optional[bool] = None


class PasswordChange(BaseModel):
    password: str


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
    scheduled_date: str
    delivery_time: str = ""                 # 배송시간 (선택)
    delivery_type: str = "출하"             # 출하 / 입하
    notes: Optional[str] = None
    # 배차 정보 (배차 권한자가 별도 설정, 생성 시 없어도 됨)
    driver_id: Optional[int] = None
    vehicle_number: Optional[str] = None


class DeliveryEdit(BaseModel):
    company: Optional[str] = None
    destination: Optional[str] = None
    item_name: Optional[str] = None
    quantity: Optional[int] = None
    scheduled_date: Optional[str] = None
    delivery_time: Optional[str] = None
    delivery_type: Optional[str] = None
    notes: Optional[str] = None


class DeliveryAssign(BaseModel):
    driver_id: int
    vehicle_number: Optional[str] = None


class DeliveryUpdate(BaseModel):
    status: Optional[str] = None
    loading_complete_time: Optional[str] = None
    driving_time: Optional[str] = None
    unloaded_time: Optional[str] = None
    complete_time: Optional[str] = None
    complete_memo: Optional[str] = None


class PhotoResponse(BaseModel):
    id: int
    photo_data: str
    drive_file_id: Optional[str] = None
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
    driver_id: Optional[int]
    vehicle_number: Optional[str]
    scheduled_date: str
    delivery_time: Optional[str] = None
    delivery_type: str = "출하"
    notes: Optional[str]
    status: str
    loading_complete_time: Optional[str]
    driving_time: Optional[str]
    unloaded_time: Optional[str]
    complete_time: Optional[str]
    complete_memo: Optional[str]
    created_at: datetime
    driver_user: Optional[UserResponse] = None
    photos: List[PhotoResponse] = []

    class Config:
        from_attributes = True
