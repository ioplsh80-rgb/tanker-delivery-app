"""단계별 안전 유의사항 (상차/하차 등) 관리.

전 고객사 공통으로 적용되며, 기사·관리자가 해당 단계를 진행할 때
한 건씩 확인하고 동의해야 넘어갈 수 있다. 단계는 확장 가능.
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

import models
import schemas
from database import get_db
from routers.auth import get_current_user

router = APIRouter()

VALID_STAGES = ("loaded", "unloaded")
STAGE_LABELS = {"loaded": "상차", "unloaded": "하차"}
MAX_PER_STAGE = 10
PHOTO_SUBFOLDER = "상하차유의사항_사진"


def _require_superadmin(current_user: models.User):
    if current_user.role != "superadmin":
        raise HTTPException(status_code=403, detail="슈퍼관리자만 안전 유의사항을 관리할 수 있습니다.")


@router.get("", response_model=List[schemas.StageNoticeResponse])
def list_stage_notices(
    stage: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """단계별 유의사항 조회 (기사 확인 절차에 필요하므로 로그인 사용자 전체 허용)"""
    q = db.query(models.StageNotice)
    if stage:
        q = q.filter(models.StageNotice.stage == stage)
    return q.order_by(models.StageNotice.stage, models.StageNotice.order_num).all()


@router.post("", response_model=schemas.StageNoticeResponse)
def add_stage_notice(
    body: schemas.StageNoticeCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    _require_superadmin(current_user)
    if body.stage not in VALID_STAGES:
        raise HTTPException(status_code=400, detail="알 수 없는 단계입니다.")
    count = db.query(models.StageNotice).filter(models.StageNotice.stage == body.stage).count()
    if count >= MAX_PER_STAGE:
        raise HTTPException(
            status_code=400,
            detail=f"{STAGE_LABELS[body.stage]} 유의사항은 최대 {MAX_PER_STAGE}개까지 등록 가능합니다.")
    notice = models.StageNotice(stage=body.stage, content=body.content, order_num=count)
    db.add(notice)
    db.commit()
    db.refresh(notice)
    return notice


@router.patch("/{notice_id}", response_model=schemas.StageNoticeResponse)
def update_stage_notice(
    notice_id: int,
    body: schemas.StageNoticeUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    _require_superadmin(current_user)
    notice = db.query(models.StageNotice).filter(models.StageNotice.id == notice_id).first()
    if not notice:
        raise HTTPException(status_code=404, detail="유의사항을 찾을 수 없습니다.")
    notice.content = body.content
    db.commit()
    db.refresh(notice)
    return notice


@router.delete("/{notice_id}")
def delete_stage_notice(
    notice_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    _require_superadmin(current_user)
    notice = db.query(models.StageNotice).filter(models.StageNotice.id == notice_id).first()
    if not notice:
        raise HTTPException(status_code=404, detail="유의사항을 찾을 수 없습니다.")
    db.delete(notice)
    db.commit()
    return {"success": True}


@router.post("/{notice_id}/photo", response_model=schemas.StageNoticeResponse)
async def upload_stage_notice_photo(
    notice_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    _require_superadmin(current_user)
    notice = db.query(models.StageNotice).filter(models.StageNotice.id == notice_id).first()
    if not notice:
        raise HTTPException(status_code=404, detail="유의사항을 찾을 수 없습니다.")
    from routers.deliveries import _upload_to_drive
    contents = await file.read()
    mime = file.content_type or "image/jpeg"
    fname = f"stage_{notice.stage}_{notice_id}_{file.filename}"
    drive_id = _upload_to_drive(contents, fname, mime, subfolder=PHOTO_SUBFOLDER)
    if not drive_id:
        raise HTTPException(status_code=500, detail="사진 업로드에 실패했습니다. 잠시 후 다시 시도해주세요.")
    notice.drive_file_id = drive_id
    db.commit()
    db.refresh(notice)
    return notice
