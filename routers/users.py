from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session
from typing import List

import models
import schemas
from database import get_db
from routers.auth import (COOKIE_NAME, TOKEN_EXPIRE_MINUTES, create_access_token,
                          get_current_user, get_password_hash, verify_password)

router = APIRouter()

PASSWORD_MIN_LENGTH = 5


def _validate_password(password: str):
    if not password or len(password) < PASSWORD_MIN_LENGTH:
        raise HTTPException(status_code=400, detail=f"비밀번호는 최소 {PASSWORD_MIN_LENGTH}자 이상이어야 합니다.")


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
    if current_user.role not in ("admin", "superadmin"):
        raise HTTPException(status_code=403, detail="관리자만 기사 목록을 조회할 수 있습니다.")
    return (
        db.query(models.User)
        .filter(models.User.role == "driver", models.User.is_active == True)
        .all()
    )


@router.get("/admins", response_model=List[schemas.UserResponse])
def get_admins(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """관리자 목록 (배송카드 공개 대상 지정용) — 관리자만 조회 가능"""
    if current_user.role not in ("admin", "superadmin"):
        raise HTTPException(status_code=403, detail="관리자만 접근 가능합니다.")
    return (
        db.query(models.User)
        .filter(models.User.role == "admin", models.User.is_active == True)
        .order_by(models.User.name)
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
    _validate_password(user.password)

    db_user = models.User(
        name=user.name,
        username=user.username,
        password_hash=get_password_hash(user.password),
        role=user.role,
        department=user.department,
        email=user.email,
        phone=user.phone,
        can_create_delivery=user.can_create_delivery,
        can_assign_vehicle=user.can_assign_vehicle,
        vehicle_number=user.vehicle_number,
        vehicle_type=user.vehicle_type,
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user


@router.patch("/{user_id}/info")
def update_user_info(
    user_id: int,
    body: schemas.UserUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    if current_user.role != "superadmin":
        raise HTTPException(status_code=403, detail="슈퍼관리자만 사용자 정보를 수정할 수 있습니다.")
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")
    if body.name is not None:
        user.name = body.name
    if body.department is not None:
        user.department = body.department
    if body.email is not None:
        user.email = body.email
    if body.phone is not None:
        user.phone = body.phone
    if body.vehicle_id is not None:
        user.vehicle_id = body.vehicle_id if body.vehicle_id != 0 else None
    if body.vehicle_number is not None:
        user.vehicle_number = body.vehicle_number if body.vehicle_number else None
    if body.vehicle_type is not None:
        user.vehicle_type = body.vehicle_type if body.vehicle_type else None
    db.commit()
    db.refresh(user)
    return user


@router.patch("/{user_id}/password")
def change_password(
    user_id: int,
    body: schemas.PasswordChange,
    response: Response,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    _validate_password(body.password)
    # 본인: 현재 비밀번호 확인 후 변경 가능 / 타인: 슈퍼관리자만 가능
    if current_user.id == user_id:
        if not body.current_password or not verify_password(body.current_password, current_user.password_hash):
            raise HTTPException(status_code=400, detail="현재 비밀번호가 일치하지 않습니다.")
    elif current_user.role != "superadmin":
        raise HTTPException(status_code=403, detail="다른 사용자의 비밀번호는 슈퍼관리자만 변경할 수 있습니다.")
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")
    user.password_hash = get_password_hash(body.password)
    # 이전에 발급된 토큰 전부 무효화 (탈취된 토큰이 있어도 비밀번호 변경으로 차단)
    user.token_valid_from = datetime.utcnow() - timedelta(seconds=1)
    db.commit()
    # 본인 변경이면 새 토큰을 재발급해 로그인 상태 유지
    if current_user.id == user_id:
        token = create_access_token({"sub": user.username})
        response.set_cookie(
            key=COOKIE_NAME, value=token,
            httponly=True, secure=True, samesite="lax",
            max_age=TOKEN_EXPIRE_MINUTES * 60, path="/",
        )
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
