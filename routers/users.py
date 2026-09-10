from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session
from typing import List

import models
import schemas
from database import get_db
from routers.auth import (create_access_token, get_current_user,
                          get_password_hash, set_auth_cookie, verify_password)

router = APIRouter()

# observer: 영업 담당자용 열람 전용. 전체 배송건을 보고 대화에는 글을 쓸 수 있다.
VALID_ROLES = ("superadmin", "admin", "observer", "driver")

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
    if current_user.role not in ("admin", "superadmin", "observer"):
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
    if current_user.role not in ("admin", "superadmin", "observer"):
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
    if user.role not in VALID_ROLES:
        raise HTTPException(status_code=400, detail=f"알 수 없는 역할입니다: {user.role}")
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
        # 열람 전용 계정은 권한 플래그를 무시하고 끈 채로 만든다
        can_create_delivery=False if user.role == "observer" else user.can_create_delivery,
        can_assign_vehicle=False if user.role == "observer" else user.can_assign_vehicle,
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
        set_auth_cookie(response, create_access_token({"sub": user.username}))
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
    # 열람 전용 계정에는 이 권한들이 의미가 없다. 켜 두면 헷갈리기만 하고,
    # 예전에는 켜면 실제로 카드 생성·배차가 통과했다.
    if user.role == "observer":
        raise HTTPException(status_code=400, detail="열람 전용 계정에는 이 권한을 줄 수 없습니다.")
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


# ── 계정 완전 삭제 (아무 데도 안 엮인 경우만) ──────────────────────────────
# 실수로 잘못 만든 계정을 치우기 위한 것이다.
# 배송·대화·유의사항 동의처럼 '한 일'이 남아 있으면 지우지 않는다.
# 지우면 지난 배송건의 기사 이름이 사라지고, 사고 때 근거가 되는 동의 기록이
# 주인을 잃는다. 그런 계정은 '비활성화' 를 써야 한다.

def _user_references(user_id: int, db: Session):
    """계정이 어디에 얼마나 엮여 있는지. 지우면 안 되는 것과 같이 지울 것을 나눈다."""
    D = models.Delivery
    blocking = {
        "담당한 배송": db.query(D).filter(D.driver_id == user_id).count(),
        "만든 배송": db.query(D).filter(D.created_by == user_id).count(),
        "배차한 배송": db.query(D).filter(D.assigned_by == user_id).count(),
        "대화 글": db.query(models.DeliveryMessage).filter(
            models.DeliveryMessage.user_id == user_id).count(),
        "유의사항 동의 기록": db.query(models.DeliveryNoticeAck).filter(
            models.DeliveryNoticeAck.user_id == user_id).count(),
    }
    # 아래는 '한 일'이 아니라 설정·기록이라 계정과 함께 지운다
    removable = {
        "배송카드 열람 지정": db.query(models.DeliveryViewer).filter(
            models.DeliveryViewer.user_id == user_id).count(),
        "대화 읽음 표시": db.query(models.DeliveryMessageRead).filter(
            models.DeliveryMessageRead.user_id == user_id).count(),
        "알림 기기 등록": db.query(models.PushSubscription).filter(
            models.PushSubscription.user_id == user_id).count(),
        "알림 발송 기록": db.query(models.PushLog).filter(
            models.PushLog.user_id == user_id).count(),
    }
    return blocking, removable


@router.get("/{user_id}/references")
def user_references(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """지울 수 있는 계정인지 미리 알아본다 (지우지는 않는다)."""
    if current_user.role != "superadmin":
        raise HTTPException(status_code=403, detail="슈퍼관리자만 확인할 수 있습니다.")
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")
    blocking, removable = _user_references(user_id, db)
    return {
        "name": user.name,
        "can_delete": sum(blocking.values()) == 0 and user.id != current_user.id
                      and user.role != "superadmin",
        "blocking": {k: v for k, v in blocking.items() if v},
        "removable": {k: v for k, v in removable.items() if v},
    }


@router.delete("/{user_id}")
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    if current_user.role != "superadmin":
        raise HTTPException(status_code=403, detail="슈퍼관리자만 삭제할 수 있습니다.")
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")
    if user.id == current_user.id:
        raise HTTPException(status_code=400, detail="본인 계정은 삭제할 수 없습니다.")
    if user.role == "superadmin":
        raise HTTPException(status_code=400, detail="슈퍼관리자 계정은 삭제할 수 없습니다.")

    blocking, _ = _user_references(user_id, db)
    left = {k: v for k, v in blocking.items() if v}
    if left:
        detail = ", ".join(f"{k} {v}건" for k, v in left.items())
        raise HTTPException(
            status_code=400,
            detail=f"이 계정은 {detail}이 남아 있어 지울 수 없습니다. "
                   f"기록이 깨지므로 '비활성화'를 사용해주세요.")

    # 설정·기록만 함께 정리한다
    for model, col in (
        (models.DeliveryViewer, models.DeliveryViewer.user_id),
        (models.DeliveryMessageRead, models.DeliveryMessageRead.user_id),
        (models.PushSubscription, models.PushSubscription.user_id),
        (models.PushLog, models.PushLog.user_id),
    ):
        db.query(model).filter(col == user_id).delete(synchronize_session=False)
    name = user.name
    db.delete(user)
    db.commit()
    return {"success": True, "name": name}
