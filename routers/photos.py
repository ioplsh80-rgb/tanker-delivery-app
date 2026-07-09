"""사진 열람 프록시.

Drive에 비공개로 저장된 사진을 서버가 권한 확인 후 스트리밍한다.
- 계근표/대화 사진: 해당 배송카드 열람 권한 필요
- 주의사항 사진: 로그인한 사용자 누구나 (기사가 봐야 하는 정보)
"""
import io
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

import models
from database import get_db
from routers.auth import get_current_user
from routers.deliveries import get_drive_service, _can_view_delivery

router = APIRouter()


def _check_photo_permission(file_id: str, db: Session, current_user: models.User):
    """drive_file_id가 어느 자료에 속하는지 찾아 열람 권한 확인."""
    photo = db.query(models.DeliveryPhoto).filter(
        models.DeliveryPhoto.drive_file_id == file_id).first()
    if photo:
        d = db.query(models.Delivery).filter(models.Delivery.id == photo.delivery_id).first()
        if not d or not _can_view_delivery(d, db, current_user):
            raise HTTPException(status_code=403, detail="이 사진에 접근할 권한이 없습니다.")
        return

    msg = db.query(models.DeliveryMessage).filter(
        models.DeliveryMessage.drive_file_id == file_id).first()
    if msg:
        d = db.query(models.Delivery).filter(models.Delivery.id == msg.delivery_id).first()
        if not d or not _can_view_delivery(d, db, current_user):
            raise HTTPException(status_code=403, detail="이 사진에 접근할 권한이 없습니다.")
        return

    notice = db.query(models.CompanyNotice).filter(
        models.CompanyNotice.drive_file_id == file_id).first()
    if notice:
        return  # 주의사항 사진은 로그인 사용자 누구나

    raise HTTPException(status_code=404, detail="사진을 찾을 수 없습니다.")


@router.get("/{file_id}")
def get_photo(
    file_id: str,
    download: int = 0,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    _check_photo_permission(file_id, db, current_user)

    service = get_drive_service()
    if not service:
        raise HTTPException(status_code=500, detail="사진 저장소 연결에 실패했습니다.")

    try:
        meta = service.files().get(fileId=file_id, fields="mimeType,name").execute()
        contents = service.files().get_media(fileId=file_id).execute()
    except Exception:
        raise HTTPException(status_code=404, detail="사진을 불러올 수 없습니다.")

    headers = {"Cache-Control": "private, max-age=3600"}
    if download:
        headers["Content-Disposition"] = f"attachment; filename*=UTF-8''{quote(meta.get('name') or 'photo.jpg')}"
    return StreamingResponse(
        io.BytesIO(contents),
        media_type=meta.get("mimeType") or "image/jpeg",
        headers=headers,
    )
