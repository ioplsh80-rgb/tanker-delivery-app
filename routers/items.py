from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

import models
import schemas
from database import get_db
from routers.auth import get_current_user

router = APIRouter()


@router.get("/", response_model=List[schemas.ItemResponse])
def get_items(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return (
        db.query(models.Item)
        .filter(models.Item.is_active == True)
        .order_by(models.Item.name)
        .all()
    )


@router.post("/", response_model=schemas.ItemResponse)
def create_item(
    item: schemas.ItemCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    if current_user.role != "superadmin":
        raise HTTPException(status_code=403, detail="슈퍼관리자만 품목을 추가할 수 있습니다.")
    existing = db.query(models.Item).filter(models.Item.name == item.name).first()
    if existing:
        if existing.is_active:
            raise HTTPException(status_code=400, detail="이미 존재하는 품목입니다.")
        # 비활성화된 품목 복원
        existing.is_active = True
        db.commit()
        db.refresh(existing)
        return existing
    db_item = models.Item(name=item.name)
    db.add(db_item)
    db.commit()
    db.refresh(db_item)
    return db_item


@router.delete("/{item_id}")
def delete_item(
    item_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    if current_user.role != "superadmin":
        raise HTTPException(status_code=403, detail="슈퍼관리자만 품목을 삭제할 수 있습니다.")
    item = db.query(models.Item).filter(models.Item.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="품목을 찾을 수 없습니다.")
    item.is_active = False
    db.commit()
    return {"success": True}
