import base64
import io
import json
import os
from datetime import datetime, timedelta, timezone
from typing import List, Optional

KST = timezone(timedelta(hours=9))

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import or_
from sqlalchemy.orm import Session

import models
import schemas
from database import get_db
from routers.auth import get_current_user


def get_drive_service():
    """Google Drive API 서비스 객체 생성. 환경변수 미비 시 None."""
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    client_id = os.getenv("GOOGLE_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
    refresh_token = os.getenv("GOOGLE_REFRESH_TOKEN")
    if not all([client_id, client_secret, refresh_token]):
        return None
    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        client_id=client_id,
        client_secret=client_secret,
        token_uri="https://oauth2.googleapis.com/token",
    )
    return build("drive", "v3", credentials=creds)


def _upload_to_drive(contents: bytes, filename: str, mime_type: str, subfolder: Optional[str] = None) -> Optional[str]:
    """Google Drive에 파일 업로드(비공개), 파일 ID 반환. 실패 시 None.
    subfolder 지정 시 기본 폴더 아래 해당 이름의 하위폴더에 저장 (없으면 생성)."""
    try:
        from googleapiclient.http import MediaIoBaseUpload

        folder_id = os.getenv("GOOGLE_DRIVE_FOLDER_ID")
        service = get_drive_service()
        if not service or not folder_id:
            return None

        if subfolder:
            q = (f"name = '{subfolder}' and mimeType = 'application/vnd.google-apps.folder' "
                 f"and '{folder_id}' in parents and trashed = false")
            res = service.files().list(q=q, fields="files(id)").execute()
            found = res.get("files", [])
            if found:
                folder_id = found[0]["id"]
            else:
                new_folder = service.files().create(
                    body={"name": subfolder, "mimeType": "application/vnd.google-apps.folder",
                          "parents": [folder_id]},
                    fields="id",
                ).execute()
                folder_id = new_folder["id"]

        file_metadata = {"name": filename, "parents": [folder_id]}
        media = MediaIoBaseUpload(io.BytesIO(contents), mimetype=mime_type)
        file = service.files().create(body=file_metadata, media_body=media, fields="id").execute()
        # 공개 권한을 걸지 않음 - 열람은 서버 프록시(/api/photos)가 권한 확인 후 제공
        return file.get("id")
    except Exception as e:
        import traceback
        print(f"[Drive 업로드 실패] {e}")
        traceback.print_exc()
        return None

router = APIRouter()

# 출하: 대기중→상차완료→운행→하차완료→완료(계근표)
OUTBOUND_FLOW = ["wait", "loaded", "driving", "unloaded", "done"]
# 입하: 대기중→운행→상차완료→완료(자동)
INBOUND_FLOW  = ["wait", "driving", "loaded", "done"]

ADMIN_ROLES = ("admin", "superadmin")

STATUS_LABELS = {
    "wait": "대기중", "loaded": "상차완료", "driving": "운행중",
    "unloaded": "하차완료", "done": "완료", "cancel": "취소",
}


def _validate_status_transition(d, new_status: str):
    """상태 변경이 출하/입하 흐름의 바로 다음 단계인지 검증."""
    flow = get_flow(d.delivery_type)
    if new_status == "cancel":
        if d.status != "wait":
            raise HTTPException(status_code=400, detail="대기중 상태에서만 취소할 수 있습니다.")
        return
    if new_status not in flow:
        raise HTTPException(status_code=400, detail="알 수 없는 상태값입니다.")
    if d.status not in flow:
        raise HTTPException(status_code=400, detail=f"현재 상태({STATUS_LABELS.get(d.status, d.status)})에서는 변경할 수 없습니다.")
    if flow.index(new_status) != flow.index(d.status) + 1:
        raise HTTPException(
            status_code=400,
            detail=f"순서에 맞지 않는 상태 변경입니다. (현재: {STATUS_LABELS.get(d.status)}, 요청: {STATUS_LABELS.get(new_status)})",
        )


def get_flow(delivery_type: str):
    return OUTBOUND_FLOW if delivery_type == "출하" else INBOUND_FLOW


def _apply_visibility_filter(query, db: Session, current_user: models.User):
    """역할별 배송카드 열람 범위 필터.
    superadmin: 전체 / driver: 본인 배차 건 / admin: 본인 생성 + 열람 지정된 건"""
    if current_user.role == "driver":
        return query.filter(models.Delivery.driver_id == current_user.id)
    if current_user.role == "admin":
        visible_ids = db.query(models.DeliveryViewer.delivery_id).filter(
            models.DeliveryViewer.user_id == current_user.id
        )
        return query.filter(or_(
            models.Delivery.created_by == current_user.id,
            models.Delivery.id.in_(visible_ids),
        ))
    return query  # superadmin


def _can_view_delivery(d: models.Delivery, db: Session, current_user: models.User) -> bool:
    if current_user.role == "superadmin":
        return True
    if current_user.role == "driver":
        return d.driver_id == current_user.id
    if d.created_by == current_user.id:
        return True
    return db.query(models.DeliveryViewer).filter(
        models.DeliveryViewer.delivery_id == d.id,
        models.DeliveryViewer.user_id == current_user.id,
    ).first() is not None


def _require_view(d: models.Delivery, db: Session, current_user: models.User):
    if not _can_view_delivery(d, db, current_user):
        raise HTTPException(status_code=403, detail="이 배송카드에 접근할 권한이 없습니다.")


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
    query = _apply_visibility_filter(db.query(models.Delivery), db, current_user)

    if current_user.role != "driver" and driver_id:
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

    db_delivery = models.Delivery(**delivery.dict(exclude={"viewer_ids"}), created_by=current_user.id)
    db.add(db_delivery)
    db.flush()
    for uid in set(delivery.viewer_ids or []):
        if uid != current_user.id:
            db.add(models.DeliveryViewer(delivery_id=db_delivery.id, user_id=uid))
    db.commit()
    db.refresh(db_delivery)
    return db_delivery


@router.patch("/{delivery_id}/viewers")
def update_viewers(
    delivery_id: int,
    body: schemas.DeliveryViewersUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """열람 허용 관리자 변경 — 카드 생성자 또는 슈퍼관리자만 가능"""
    d = db.query(models.Delivery).filter(models.Delivery.id == delivery_id).first()
    if not d:
        raise HTTPException(status_code=404, detail="배송을 찾을 수 없습니다.")
    if current_user.role != "superadmin" and d.created_by != current_user.id:
        raise HTTPException(status_code=403, detail="카드 생성자 또는 슈퍼관리자만 공개 대상을 변경할 수 있습니다.")
    db.query(models.DeliveryViewer).filter(models.DeliveryViewer.delivery_id == delivery_id).delete()
    for uid in set(body.viewer_ids or []):
        if uid != d.created_by:
            db.add(models.DeliveryViewer(delivery_id=delivery_id, user_id=uid))
    db.commit()
    return {"success": True}


# ── 배송카드 대화 ──────────────────────────────────────
CHAT_PHOTO_SUBFOLDER = "배송대화_사진"


def _get_delivery_for_chat(delivery_id: int, db: Session, current_user: models.User) -> models.Delivery:
    d = db.query(models.Delivery).filter(models.Delivery.id == delivery_id).first()
    if not d:
        raise HTTPException(status_code=404, detail="배송을 찾을 수 없습니다.")
    _require_view(d, db, current_user)
    return d


def _message_response(m: models.DeliveryMessage) -> schemas.MessageResponse:
    return schemas.MessageResponse(
        id=m.id,
        delivery_id=m.delivery_id,
        user_id=m.user_id,
        user_name=m.user.name if m.user else "-",
        user_role=m.user.role if m.user else "",
        content=m.content or "",
        drive_file_id=m.drive_file_id,
        created_at=m.created_at,
    )


def _mark_read(delivery_id: int, db: Session, current_user: models.User):
    read = db.query(models.DeliveryMessageRead).filter(
        models.DeliveryMessageRead.delivery_id == delivery_id,
        models.DeliveryMessageRead.user_id == current_user.id,
    ).first()
    now = datetime.utcnow()
    if read:
        read.last_read_at = now
    else:
        db.add(models.DeliveryMessageRead(
            delivery_id=delivery_id, user_id=current_user.id, last_read_at=now,
        ))


@router.get("/unread-counts")
def get_unread_counts(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """배송카드별 안 읽은 메시지 개수 { delivery_id: count }"""
    q = _apply_visibility_filter(db.query(models.Delivery.id), db, current_user)
    ids = [r[0] for r in q.all()]
    if not ids:
        return {}
    reads = {
        r.delivery_id: r.last_read_at
        for r in db.query(models.DeliveryMessageRead).filter(
            models.DeliveryMessageRead.user_id == current_user.id,
            models.DeliveryMessageRead.delivery_id.in_(ids),
        ).all()
    }
    msgs = db.query(models.DeliveryMessage).filter(
        models.DeliveryMessage.delivery_id.in_(ids),
        models.DeliveryMessage.user_id != current_user.id,
    ).all()
    counts = {}
    for m in msgs:
        last_read = reads.get(m.delivery_id)
        if last_read is None or m.created_at > last_read:
            counts[m.delivery_id] = counts.get(m.delivery_id, 0) + 1
    return counts


@router.get("/{delivery_id}/messages", response_model=List[schemas.MessageResponse])
def get_messages(
    delivery_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    _get_delivery_for_chat(delivery_id, db, current_user)
    msgs = (
        db.query(models.DeliveryMessage)
        .filter(models.DeliveryMessage.delivery_id == delivery_id)
        .order_by(models.DeliveryMessage.created_at)
        .all()
    )
    _mark_read(delivery_id, db, current_user)
    db.commit()
    return [_message_response(m) for m in msgs]


@router.post("/{delivery_id}/messages", response_model=schemas.MessageResponse)
def send_message(
    delivery_id: int,
    body: schemas.MessageCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    _get_delivery_for_chat(delivery_id, db, current_user)
    content = (body.content or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="메시지 내용을 입력해주세요.")
    m = models.DeliveryMessage(delivery_id=delivery_id, user_id=current_user.id, content=content)
    db.add(m)
    _mark_read(delivery_id, db, current_user)
    db.commit()
    db.refresh(m)
    return _message_response(m)


@router.post("/{delivery_id}/messages/photo", response_model=schemas.MessageResponse)
async def send_photo_message(
    delivery_id: int,
    file: UploadFile = File(...),
    content: str = Form(""),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    _get_delivery_for_chat(delivery_id, db, current_user)
    contents = await file.read()
    mime = file.content_type or "image/jpeg"
    fname = f"chat_D{delivery_id}_{file.filename or 'photo.jpg'}"
    drive_id = _upload_to_drive(contents, fname, mime, subfolder=CHAT_PHOTO_SUBFOLDER)
    if not drive_id:
        raise HTTPException(status_code=500, detail="사진 업로드에 실패했습니다.")
    m = models.DeliveryMessage(
        delivery_id=delivery_id, user_id=current_user.id,
        content=(content or "").strip(), drive_file_id=drive_id,
    )
    db.add(m)
    _mark_read(delivery_id, db, current_user)
    db.commit()
    db.refresh(m)
    return _message_response(m)


# ── 유의사항 확인(동의) 기록 ──────────────────────────
@router.get("/{delivery_id}/notice-ack")
def get_notice_acks(
    delivery_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """이 배송카드의 유의사항 확인 기록 목록"""
    d = db.query(models.Delivery).filter(models.Delivery.id == delivery_id).first()
    if not d:
        raise HTTPException(status_code=404, detail="배송을 찾을 수 없습니다.")
    _require_view(d, db, current_user)
    acks = db.query(models.DeliveryNoticeAck).filter(
        models.DeliveryNoticeAck.delivery_id == delivery_id).all()
    return [
        {"user_id": a.user_id, "user_name": a.user.name if a.user else "-",
         "agreed_at": a.agreed_at.isoformat()}
        for a in acks
    ]


@router.post("/{delivery_id}/notice-ack")
def create_notice_ack(
    delivery_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """유의사항 확인(동의) 기록 - 동의 시점의 유의사항 전문을 함께 저장"""
    d = db.query(models.Delivery).filter(models.Delivery.id == delivery_id).first()
    if not d:
        raise HTTPException(status_code=404, detail="배송을 찾을 수 없습니다.")
    _require_view(d, db, current_user)

    existing = db.query(models.DeliveryNoticeAck).filter(
        models.DeliveryNoticeAck.delivery_id == delivery_id,
        models.DeliveryNoticeAck.user_id == current_user.id,
    ).first()
    if existing:
        return {"success": True, "already": True}

    # 동의 시점의 유의사항 내용을 증빙으로 저장
    company = db.query(models.Company).filter(models.Company.name == d.company).first()
    snapshot = []
    if company:
        snapshot = [
            {"content": n.content, "drive_file_id": n.drive_file_id}
            for n in company.notices
        ]
    db.add(models.DeliveryNoticeAck(
        delivery_id=delivery_id, user_id=current_user.id,
        notices_snapshot=json.dumps(snapshot, ensure_ascii=False),
    ))
    db.commit()
    return {"success": True}


@router.get("/{delivery_id}", response_model=schemas.DeliveryResponse)
def get_delivery(
    delivery_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    d = db.query(models.Delivery).filter(models.Delivery.id == delivery_id).first()
    if not d:
        raise HTTPException(status_code=404, detail="배송을 찾을 수 없습니다.")
    _require_view(d, db, current_user)
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
    _require_view(d, db, current_user)

    # 기사는 7일 이내 배송만 수정 가능
    if current_user.role == "driver":
        from datetime import timedelta
        cutoff = (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%d")
        if d.scheduled_date < cutoff:
            raise HTTPException(status_code=403, detail="7일이 지난 배송은 수정할 수 없습니다.")

    if update.status:
        _validate_status_transition(d, update.status)
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
    _require_view(d, db, current_user)
    d.driver_id = assign.driver_id
    if assign.vehicle_number:
        d.vehicle_number = assign.vehicle_number
    else:
        driver = db.query(models.User).filter(models.User.id == assign.driver_id).first()
        if driver and driver.vehicle_number:
            d.vehicle_number = driver.vehicle_number
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
    _require_view(d, db, current_user)

    # 취소 철회: 취소 상태는 대기중으로 복구
    if d.status == "cancel":
        d.status = "wait"
        d.updated_at = datetime.utcnow()
        db.commit()
        return {"success": True, "new_status": "wait"}

    flow = get_flow(d.delivery_type)

    if d.status not in flow:
        raise HTTPException(status_code=400, detail="되돌릴 수 없는 상태입니다.")

    idx = flow.index(d.status)
    if idx == 0:
        raise HTTPException(status_code=400, detail="이미 첫 번째 단계(대기중)입니다.")

    prev_status = flow[idx - 1]
    d.status = prev_status

    # 되돌린 지점보다 뒤 단계의 시간 기록만 초기화 (출하/입하 흐름 각각 기준)
    status_time_fields = {
        "loaded": "loading_complete_time",
        "driving": "driving_time",
        "unloaded": "unloaded_time",
        "done": "complete_time",
    }
    for later_status in flow[idx:]:
        field = status_time_fields.get(later_status)
        if field:
            setattr(d, field, None)
        if later_status == "done":
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
    _require_view(d, db, current_user)

    # 완료 직전 단계(출하: 하차완료, 입하: 상차완료)에서만 계근표 등록 가능
    flow = get_flow(d.delivery_type)
    if d.status != flow[-2]:
        raise HTTPException(
            status_code=400,
            detail=f"{STATUS_LABELS.get(flow[-2])} 상태에서만 계근표를 등록할 수 있습니다. (현재: {STATUS_LABELS.get(d.status, d.status)})",
        )

    for file in files:
        contents = await file.read()
        mime = file.content_type or "image/jpeg"
        fname = file.filename or "photo.jpg"

        drive_id = _upload_to_drive(contents, fname, mime)
        if drive_id:
            db.add(models.DeliveryPhoto(
                delivery_id=delivery_id,
                photo_data="",
                drive_file_id=drive_id,
                filename=fname,
            ))
        else:
            photo_data = f"data:{mime};base64," + base64.b64encode(contents).decode()
            db.add(models.DeliveryPhoto(
                delivery_id=delivery_id,
                photo_data=photo_data,
                filename=fname,
            ))

    d.status = "done"
    d.complete_time = datetime.now(KST).strftime("%H:%M")
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
    _require_view(d, db, current_user)
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
    _require_view(d, db, current_user)
    db.query(models.DeliveryMessage).filter(models.DeliveryMessage.delivery_id == delivery_id).delete()
    db.query(models.DeliveryViewer).filter(models.DeliveryViewer.delivery_id == delivery_id).delete()
    db.query(models.DeliveryMessageRead).filter(models.DeliveryMessageRead.delivery_id == delivery_id).delete()
    db.delete(d)
    db.commit()
    return {"success": True}
