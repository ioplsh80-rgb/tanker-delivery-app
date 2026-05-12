import base64
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

import models
import schemas
from database import get_db
from routers.auth import get_current_user

router = APIRouter()

# 출하: 대기중→상차완료→운행→하차완료→완료(계근표)
OUTBOUND_FLOW = ["wait", "loaded", "driving", "unloaded", "done"]
# 입하: 대기중→운행→상차완료→완료(자동)
INBOUND_FLOW  = ["wait", "driving", "loaded", "done"]

ADMIN_ROLES = ("admin", "superadmin")


def get_flow(delivery_type: str):
    return OUTBOUND_FLOW if delivery_type == "출하" else INBOUND_FLOW


@router.get("/", response_model=List[schemas.DeliveryResponse])
def get_deliveries(
    status: Optional[str] = None,
    driver_id: Optional[int] = None,
    date: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    query = db.query(models.Delivery)

    if current_user.role == "driver":
        query = query.filter(models.Delivery.driver_id == current_user.id)
    else:
        if driver_id:
            query = query.filter(models.Delivery.driver_id == driver_id)

    if status:
        query = query.filter(models.Delivery.status == status)
    if date:
        query = query.filter(models.Delivery.scheduled_date == date)
    if date_from:
        query = query.filter(models.Delivery.scheduled_date >= date_from)
    if date_to:
        query = query.filter(models.Delivery.scheduled_date <= date_to)

    return (
        query.order_by(models.Delivery.scheduled_date.desc(), models.Delivery.delivery_time)
        .all()
    )


@router.post("/", response_model=schemas.DeliveryResponse)
def create_delivery(
    delivery: schemas.DeliveryCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    if current_user.role != "superadmin" and not current_user.can_create_delivery:
        raise HTTPException(status_code=403, detail="배송 카드 생성 권한이 없습니다.")

    db_delivery = models.Delivery(**delivery.dict(), created_by=current_user.id)
    db.add(db_delivery)
    db.commit()
    db.refresh(db_delivery)
    return db_delivery


@router.get("/{delivery_id}", response_model=schemas.DeliveryResponse)
def get_delivery(
    delivery_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    d = db.query(models.Delivery).filter(models.Delivery.id == delivery_id).first()
    if not d:
        raise HTTPException(status_code=404, detail="배송을 찾을 수 없습니다.")
    return d


@router.patch("/{delivery_id}/status")
def update_status(
    delivery_id: int,
    update: schemas.DeliveryUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    d = db.query(models.Delivery).filter(models.Delivery.id == delivery_id).first()
    if not d:
        raise HTTPException(status_code=404, detail="배송을 찾을 수 없습니다.")

    # 기사는 7일 이내 배송만 수정 가능
    if current_user.role == "driver":
        from datetime import timedelta
        cutoff = (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%d")
        if d.scheduled_date < cutoff:
            raise HTTPException(status_code=403, detail="7일이 지난 배송은 수정할 수 없습니다.")

    if update.status:
        d.status = update.status
    if update.loading_complete_time:
        d.loading_complete_time = update.loading_complete_time
    if update.driving_time:
        d.driving_time = update.driving_time
    if update.unloaded_time:
        d.unloaded_time = update.unloaded_time
    if update.complete_time:
        d.complete_time = update.complete_time
    if update.complete_memo is not None:
        d.complete_memo = update.complete_memo

    d.updated_at = datetime.utcnow()
    db.commit()
    return {"success": True}


@router.patch("/{delivery_id}/assign")
def assign_vehicle(
    delivery_id: int,
    assign: schemas.DeliveryAssign,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """배차 권한자: 기사/차량 배정"""
    if current_user.role != "superadmin" and not current_user.can_assign_vehicle:
        raise HTTPException(status_code=403, detail="배차 권한이 없습니다.")
    d = db.query(models.Delivery).filter(models.Delivery.id == delivery_id).first()
    if not d:
        raise HTTPException(status_code=404, detail="배송을 찾을 수 없습니다.")
    d.driver_id = assign.driver_id
    d.vehicle_number = assign.vehicle_number
    d.updated_at = datetime.utcnow()
    db.commit()
    return {"success": True}


@router.patch("/{delivery_id}/revert")
def revert_status(
    delivery_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """관리자 전용: 상태를 이전 단계로 되돌리기"""
    if current_user.role != "superadmin" and not (current_user.can_create_delivery or current_user.can_assign_vehicle):
        raise HTTPException(status_code=403, detail="권한이 없습니다.")

    d = db.query(models.Delivery).filter(models.Delivery.id == delivery_id).first()
    if not d:
        raise HTTPException(status_code=404, detail="배송을 찾을 수 없습니다.")

    flow = get_flow(d.delivery_type)

    if d.status not in flow:
        raise HTTPException(status_code=400, detail="되돌릴 수 없는 상태입니다.")

    idx = flow.index(d.status)
    if idx == 0:
        raise HTTPException(status_code=400, detail="이미 첫 번째 단계(대기중)입니다.")

    prev_status = flow[idx - 1]
    d.status = prev_status

    # 이후 단계 시간 초기화
    if prev_status == "wait":
        d.loading_complete_time = None
        d.driving_time = None
        d.unloaded_time = None
        d.complete_time = None
        d.complete_memo = None
    elif prev_status == "loaded":
        d.driving_time = None
        d.unloaded_time = None
        d.complete_time = None
        d.complete_memo = None
    elif prev_status == "driving":
        d.unloaded_time = None
        d.loading_complete_time = None
        d.complete_time = None
        d.complete_memo = None
    elif prev_status == "unloaded":
        d.complete_time = None
        d.complete_memo = None

    d.updated_at = datetime.utcnow()
    db.commit()
    return {"success": True, "new_status": prev_status}


@router.post("/{delivery_id}/photos")
async def upload_photos(
    delivery_id: int,
    files: List[UploadFile] = File(...),
    complete_memo: str = Form(""),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    d = db.query(models.Delivery).filter(models.Delivery.id == delivery_id).first()
    if not d:
        raise HTTPException(status_code=404, detail="배송을 찾을 수 없습니다.")
    if d.driver_id != current_user.id and current_user.role not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="권한이 없습니다.")

    for file in files:
        contents = await file.read()
        mime = file.content_type or "image/jpeg"
        photo_data = f"data:{mime};base64," + base64.b64encode(contents).decode()
        db.add(models.DeliveryPhoto(
            delivery_id=delivery_id,
            photo_data=photo_data,
            filename=file.filename,
        ))

    d.status = "done"
    d.complete_time = datetime.now().strftime("%H:%M")
    d.complete_memo = complete_memo
    d.updated_at = datetime.utcnow()
    db.commit()
    return {"success": True, "photos_uploaded": len(files)}


@router.patch("/{delivery_id}/edit")
def edit_delivery(
    delivery_id: int,
    body: schemas.DeliveryEdit,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """배송정보 권한자: 배송 카드 내용 수정"""
    if current_user.role != "superadmin" and not current_user.can_create_delivery:
        raise HTTPException(status_code=403, detail="배송 정보 수정 권한이 없습니다.")
    d = db.query(models.Delivery).filter(models.Delivery.id == delivery_id).first()
    if not d:
        raise HTTPException(status_code=404, detail="배송을 찾을 수 없습니다.")
    if body.company is not None:
        d.company = body.company
    if body.destination is not None:
        d.destination = body.destination
    if body.item_name is not None:
        d.item_name = body.item_name
    if body.quantity is not None:
        d.quantity = body.quantity
    if body.scheduled_date is not None:
        d.scheduled_date = body.scheduled_date
    if body.delivery_time is not None:
        d.delivery_time = body.delivery_time
    if body.delivery_type is not None:
        d.delivery_type = body.delivery_type
    if body.notes is not None:
        d.notes = body.notes
    d.updated_at = datetime.utcnow()
    db.commit()
    return {"success": True}


@router.delete("/{delivery_id}")
def delete_delivery(
    delivery_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    if current_user.role not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="관리자만 삭제할 수 있습니다.")
    d = db.query(models.Delivery).filter(models.Delivery.id == delivery_id).first()
    if not d:
        raise HTTPException(status_code=404, detail="배송을 찾을 수 없습니다.")
    db.delete(d)
    db.commit()
    return {"success": True}
