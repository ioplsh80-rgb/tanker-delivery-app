from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
from typing import List
import io, os, json

import models
import schemas
from database import get_db
from routers.auth import get_current_user

router = APIRouter()


@router.get("", response_model=List[schemas.CompanyResponse])
def get_companies(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return (
        db.query(models.Company)
        .filter(models.Company.is_active == True)
        .order_by(models.Company.name)
        .all()
    )


@router.post("", response_model=schemas.CompanyResponse)
def create_company(
    company: schemas.CompanyCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    if current_user.role not in ("admin", "superadmin"):
        raise HTTPException(status_code=403, detail="관리자만 고객사를 추가할 수 있습니다.")
    existing = db.query(models.Company).filter(models.Company.name == company.name).first()
    if existing:
        if existing.is_active:
            raise HTTPException(status_code=400, detail="이미 존재하는 고객사입니다.")
        existing.is_active = True
        existing.address = company.address
        existing.contact_name = company.contact_name
        existing.contact_email = company.contact_email
        existing.contact_phone = company.contact_phone
        existing.notes = company.notes
        db.commit()
        db.refresh(existing)
        return existing
    db_company = models.Company(
        name=company.name,
        address=company.address,
        contact_name=company.contact_name,
        contact_email=company.contact_email,
        contact_phone=company.contact_phone,
        notes=company.notes,
    )
    db.add(db_company)
    db.commit()
    db.refresh(db_company)
    return db_company


@router.patch("/{company_id}", response_model=schemas.CompanyResponse)
def update_company(
    company_id: int,
    body: schemas.CompanyUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    if current_user.role != "superadmin":
        raise HTTPException(status_code=403, detail="슈퍼관리자만 고객사를 수정할 수 있습니다.")
    company = db.query(models.Company).filter(models.Company.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="고객사를 찾을 수 없습니다.")
    if body.name is not None:
        company.name = body.name
    if body.address is not None:
        company.address = body.address
    if body.contact_name is not None:
        company.contact_name = body.contact_name
    if body.contact_email is not None:
        company.contact_email = body.contact_email
    if body.contact_phone is not None:
        company.contact_phone = body.contact_phone
    if body.notes is not None:
        company.notes = body.notes
    db.commit()
    db.refresh(company)
    return company


def _upload_notice_photo(contents: bytes, filename: str, mime_type: str):
    """주의사항 사진을 Drive에 비공개 업로드 (열람은 /api/photos 프록시 경유)."""
    from routers.deliveries import _upload_to_drive
    return _upload_to_drive(contents, filename, mime_type, subfolder="주의사항_사진")


@router.post("/{company_id}/notices", response_model=schemas.CompanyNoticeResponse)
def add_notice(
    company_id: int,
    body: schemas.CompanyNoticeCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    if current_user.role not in ("admin", "superadmin"):
        raise HTTPException(status_code=403, detail="관리자만 주의사항을 추가할 수 있습니다.")
    company = db.query(models.Company).filter(models.Company.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="고객사를 찾을 수 없습니다.")
    count = db.query(models.CompanyNotice).filter(models.CompanyNotice.company_id == company_id).count()
    if count >= 10:
        raise HTTPException(status_code=400, detail="주의사항은 최대 10개까지 등록 가능합니다.")
    notice = models.CompanyNotice(company_id=company_id, content=body.content, order_num=count)
    db.add(notice)
    db.commit()
    db.refresh(notice)
    return notice


@router.patch("/{company_id}/notices/{notice_id}", response_model=schemas.CompanyNoticeResponse)
def update_notice(
    company_id: int,
    notice_id: int,
    body: schemas.CompanyNoticeUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    if current_user.role not in ("admin", "superadmin"):
        raise HTTPException(status_code=403, detail="관리자만 주의사항을 수정할 수 있습니다.")
    notice = db.query(models.CompanyNotice).filter(
        models.CompanyNotice.id == notice_id,
        models.CompanyNotice.company_id == company_id
    ).first()
    if not notice:
        raise HTTPException(status_code=404, detail="주의사항을 찾을 수 없습니다.")
    notice.content = body.content
    db.commit()
    db.refresh(notice)
    return notice


@router.delete("/{company_id}/notices/{notice_id}")
def delete_notice(
    company_id: int,
    notice_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    if current_user.role not in ("admin", "superadmin"):
        raise HTTPException(status_code=403, detail="관리자만 주의사항을 삭제할 수 있습니다.")
    notice = db.query(models.CompanyNotice).filter(
        models.CompanyNotice.id == notice_id,
        models.CompanyNotice.company_id == company_id
    ).first()
    if not notice:
        raise HTTPException(status_code=404, detail="주의사항을 찾을 수 없습니다.")
    db.delete(notice)
    db.commit()
    return {"success": True}


@router.post("/{company_id}/notices/{notice_id}/photo", response_model=schemas.CompanyNoticeResponse)
async def upload_notice_photo(
    company_id: int,
    notice_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    if current_user.role not in ("admin", "superadmin"):
        raise HTTPException(status_code=403, detail="관리자만 사진을 업로드할 수 있습니다.")
    notice = db.query(models.CompanyNotice).filter(
        models.CompanyNotice.id == notice_id,
        models.CompanyNotice.company_id == company_id
    ).first()
    if not notice:
        raise HTTPException(status_code=404, detail="주의사항을 찾을 수 없습니다.")
    contents = await file.read()
    mime = file.content_type or "image/jpeg"
    fname = f"notice_{company_id}_{notice_id}_{file.filename}"
    drive_id = _upload_notice_photo(contents, fname, mime)
    if not drive_id:
        raise HTTPException(status_code=500, detail="사진 업로드에 실패했습니다. 잠시 후 다시 시도해주세요.")
    notice.drive_file_id = drive_id
    db.commit()
    db.refresh(notice)
    return notice


@router.delete("/{company_id}")
def delete_company(
    company_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    if current_user.role not in ("admin", "superadmin"):
        raise HTTPException(status_code=403, detail="관리자만 고객사를 삭제할 수 있습니다.")
    company = db.query(models.Company).filter(models.Company.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="고객사를 찾을 수 없습니다.")
    company.is_active = False
    db.commit()
    return {"success": True}
