from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

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
