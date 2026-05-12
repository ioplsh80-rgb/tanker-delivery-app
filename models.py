from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Boolean
from sqlalchemy.orm import relationship
from datetime import datetime
from database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(50), nullable=False)
    username = Column(String(50), unique=True, nullable=False, index=True)
    password_hash = Column(String(200), nullable=False)
    role = Column(String(10), nullable=False)          # superadmin / admin / driver
    department = Column(String(100))                   # 소속
    email = Column(String(200))                        # 메일주소
    phone = Column(String(50))                         # 연락처
    can_create_delivery = Column(Boolean, default=False)  # 배송정보 입력 권한
    can_assign_vehicle = Column(Boolean, default=False)   # 배차 권한
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    deliveries = relationship("Delivery", back_populates="driver_user", foreign_keys="[Delivery.driver_id]")


class Company(Base):
    """고객사 관리"""
    __tablename__ = "companies"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False)
    address = Column(String(200))
    contact_name = Column(String(100))                 # 담당자 성명
    contact_email = Column(String(200))                # 담당자 메일
    contact_phone = Column(String(50))                 # 담당자 연락처
    notes = Column(Text)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Item(Base):
    """품목 관리"""
    __tablename__ = "items"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Delivery(Base):
    __tablename__ = "deliveries"

    id = Column(Integer, primary_key=True, index=True)
    company = Column(String(100), nullable=False)           # 업체명
    destination = Column(String(200), nullable=False)       # 목적지
    item_name = Column(String(100), nullable=False)         # 품목
    quantity = Column(Integer, nullable=False)              # 수량 (Kg)
    driver_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    vehicle_number = Column(String(20))                     # 차량번호 (배송마다 별도 지정)
    scheduled_date = Column(String(10), nullable=False)     # 배송 날짜
    delivery_time = Column(String(5), nullable=False)       # 배송 시간

    delivery_type = Column(String(10), default="출하")       # 출하 / 입하
    notes = Column(Text)                                    # 특이사항

    # 상태: wait / loaded / driving / unloaded / done / cancel
    # 출하: wait→loaded→driving→unloaded→done
    # 입하: wait→driving→loaded→done
    status = Column(String(10), default="wait")

    # 단계별 시간 기록
    loading_complete_time = Column(String(5))  # 상차 완료
    driving_time = Column(String(5))           # 운행 시작
    unloaded_time = Column(String(5))          # 하차 완료
    complete_time = Column(String(5))          # 완료
    complete_memo = Column(Text)

    created_by = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    driver_user = relationship("User", foreign_keys=[driver_id], back_populates="deliveries")
    creator = relationship("User", foreign_keys=[created_by])
    photos = relationship("DeliveryPhoto", back_populates="delivery", cascade="all, delete-orphan")


class Vehicle(Base):
    __tablename__ = "vehicles"

    id = Column(Integer, primary_key=True, index=True)
    vehicle_number = Column(String(20), unique=True, nullable=False)
    vehicle_type = Column(String(50))
    capacity = Column(Integer)                             # 최대 적재량 (Kg)
    notes = Column(Text)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class DeliveryPhoto(Base):
    __tablename__ = "delivery_photos"

    id = Column(Integer, primary_key=True, index=True)
    delivery_id = Column(Integer, ForeignKey("deliveries.id"), nullable=False)
    photo_data = Column(Text, nullable=False)              # base64 인코딩
    filename = Column(String(200))
    uploaded_at = Column(DateTime, default=datetime.utcnow)

    delivery = relationship("Delivery", back_populates="photos")
