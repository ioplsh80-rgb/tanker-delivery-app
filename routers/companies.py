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
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="관리자만 고객사를 추가할 수 있습니다.")
    existing = db.query(models.Company).filter(models.Company.name == company.name).first()
    if existing:
        if existing.is_active:
            raise HTTPException(status_code=400, detail="이미 존재하는 고객사입니다.")
        existing.is_active = True
        existing.address = company.address
        existing.notes = company.notes
        db.commit()
        db.refresh(existing)
        return existing
    db_company = models.Company(name=company.name, address=company.address, notes=company.notes)
    db.add(db_company)
    db.commit()
    db.refresh(db_company)
    return db_company


@router.delete("/{company_id}")
def delete_company(
    company_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="관리자만 고객사를 삭제할 수 있습니다.")
    company = db.query(models.Company).filter(models.Company.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="고객사를 찾을 수 없습니다.")
    company.is_active = False
    db.commit()
    return {"success": True}
