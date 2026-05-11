from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

import models
import schemas
from database import get_db
from routers.auth import get_current_user, get_password_hash

router = APIRouter()


@router.get("/", response_model=List[schemas.UserResponse])
def get_all_users(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    if current_user.role != "superadmin":
        raise HTTPException(status_code=403, detail="슈퍼관리자만 접근 가능합니다.")
    return db.query(models.User).filter(models.User.is_active == True).all()


@router.get("/drivers", response_model=List[schemas.UserResponse])
def get_drivers(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return (
        db.query(models.User)
        .filter(models.User.role == "driver", models.User.is_active == True)
        .all()
    )


@router.post("/", response_model=schemas.UserResponse)
def create_user(
    user: schemas.UserCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    if current_user.role != "superadmin":
        raise HTTPException(status_code=403, detail="슈퍼관리자만 사용자를 생성할 수 있습니다.")
    if db.query(models.User).filter(models.User.username == user.username).first():
        raise HTTPException(status_code=400, detail="이미 사용 중인 아이디입니다.")

    db_user = models.User(
        name=user.name,
        username=user.username,
        password_hash=get_password_hash(user.password),
        role=user.role,
        can_create_delivery=user.can_create_delivery,
        can_assign_vehicle=user.can_assign_vehicle,
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user


@router.patch("/{user_id}/password")
def change_password(
    user_id: int,
    body: dict,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    # 본인 또는 관리자만 변경 가능
    if current_user.id != user_id and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="권한이 없습니다.")
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")
    user.password_hash = get_password_hash(body.get("password", ""))
    db.commit()
    return {"success": True}


@router.patch("/{user_id}/permissions")
def update_permissions(
    user_id: int,
    body: schemas.UserPermissionUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    if current_user.role != "superadmin":
        raise HTTPException(status_code=403, detail="슈퍼관리자만 권한을 변경할 수 있습니다.")
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")
    if body.can_create_delivery is not None:
        user.can_create_delivery = body.can_create_delivery
    if body.can_assign_vehicle is not None:
        user.can_assign_vehicle = body.can_assign_vehicle
    db.commit()
    return {"success": True}


@router.patch("/{user_id}/deactivate")
def deactivate_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    if current_user.role != "superadmin":
        raise HTTPException(status_code=403, detail="슈퍼관리자만 비활성화할 수 있습니다.")
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")
    user.is_active = False
    db.commit()
    return {"success": True}
