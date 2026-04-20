from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime

import models
from database import get_db
from routers.auth import get_current_user

router = APIRouter()


# ── 스키마 ──────────────────────────────────────────
class VehicleCreate(BaseModel):
    vehicle_number: str
    vehicle_type: Optional[str] = None
    capacity: Optional[int] = None
    notes: Optional[str] = None


class VehicleResponse(BaseModel):
    id: int
    vehicle_number: str
    vehicle_type: Optional[str]
    capacity: Optional[int]
    notes: Optional[str]
    is_active: bool

    class Config:
        from_attributes = True


# ── 엔드포인트 ──────────────────────────────────────
@router.get("/", response_model=List[VehicleResponse])
def get_vehicles(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return db.query(models.Vehicle).filter(models.Vehicle.is_active == True).all()


@router.post("/", response_model=VehicleResponse)
def create_vehicle(
    vehicle: VehicleCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="관리자만 차량을 추가할 수 있습니다.")
    existing = db.query(models.Vehicle).filter(models.Vehicle.vehicle_number == vehicle.vehicle_number).first()
    if existing:
        raise HTTPException(status_code=400, detail="이미 등록된 차량 번호입니다.")
    db_vehicle = models.Vehicle(**vehicle.dict())
    db.add(db_vehicle)
    db.commit()
    db.refresh(db_vehicle)
    return db_vehicle


@router.patch("/{vehicle_id}", response_model=VehicleResponse)
def update_vehicle(
    vehicle_id: int,
    vehicle: VehicleCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="관리자만 수정할 수 있습니다.")
    v = db.query(models.Vehicle).filter(models.Vehicle.id == vehicle_id).first()
    if not v:
        raise HTTPException(status_code=404, detail="차량을 찾을 수 없습니다.")
    for key, val in vehicle.dict().items():
        setattr(v, key, val)
    db.commit()
    db.refresh(v)
    return v


@router.delete("/{vehicle_id}")
def delete_vehicle(
    vehicle_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="관리자만 삭제할 수 있습니다.")
    v = db.query(models.Vehicle).filter(models.Vehicle.id == vehicle_id).first()
    if not v:
        raise HTTPException(status_code=404, detail="차량을 찾을 수 없습니다.")
    v.is_active = False
    db.commit()
    return {"success": True}
