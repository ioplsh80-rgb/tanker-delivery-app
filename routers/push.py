"""푸시 알림.

- 브라우저(설치된 PWA 포함)의 푸시 구독을 등록하고,
- 배송 이벤트 발생 시 대상 사용자의 모든 기기로 알림을 발송한다.
- VAPID 비밀키(VAPID_PRIVATE_KEY)가 환경변수에 없으면 발송은 조용히 건너뜀.
"""
import json
import os

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

import models
from database import get_db, SessionLocal
from routers.auth import get_current_user

router = APIRouter()

# 공개키는 비밀이 아니므로 코드에 포함 (비밀키는 Railway 환경변수)
VAPID_PUBLIC_KEY = "BIOkfa3-fFqHMrnLLScvNAnXNXl0MEEUthNXVhB7hfejdKLeBDHYZTEW2G-1LGWfSxwP9FR18rXyvP83UaWKbCk"
VAPID_CLAIMS = {"sub": "mailto:ioplsh80@gmail.com"}


class SubscriptionBody(BaseModel):
    subscription: dict


@router.get("/public-key")
def public_key():
    return {"key": VAPID_PUBLIC_KEY}


@router.post("/subscribe")
def subscribe(
    body: SubscriptionBody,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    endpoint = body.subscription.get("endpoint", "")
    if not endpoint:
        return {"success": False}
    existing = db.query(models.PushSubscription).filter(
        models.PushSubscription.endpoint == endpoint).first()
    if existing:
        existing.user_id = current_user.id  # 기기 주인이 바뀐 경우(공용폰 등) 갱신
        existing.subscription_json = json.dumps(body.subscription)
    else:
        db.add(models.PushSubscription(
            user_id=current_user.id,
            endpoint=endpoint,
            subscription_json=json.dumps(body.subscription),
        ))
    db.commit()
    return {"success": True}


@router.post("/unsubscribe")
def unsubscribe(
    body: SubscriptionBody,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    endpoint = body.subscription.get("endpoint", "")
    db.query(models.PushSubscription).filter(
        models.PushSubscription.endpoint == endpoint,
        models.PushSubscription.user_id == current_user.id,
    ).delete()
    db.commit()
    return {"success": True}


def send_push_to_users(user_ids, title: str, message: str, url: str = "/"):
    """대상 사용자들의 모든 기기로 푸시 발송 (백그라운드 작업용).
    실패한(만료된) 구독은 자동 정리한다."""
    private_key = os.getenv("VAPID_PRIVATE_KEY")
    if not private_key or not user_ids:
        return
    try:
        from pywebpush import webpush, WebPushException
    except ImportError:
        return

    payload = json.dumps({"title": title, "body": message, "url": url}, ensure_ascii=False)
    db = SessionLocal()
    try:
        subs = db.query(models.PushSubscription).filter(
            models.PushSubscription.user_id.in_(list(set(user_ids)))).all()
        for sub in subs:
            try:
                webpush(
                    subscription_info=json.loads(sub.subscription_json),
                    data=payload,
                    vapid_private_key=private_key,
                    vapid_claims=dict(VAPID_CLAIMS),
                )
            except WebPushException as e:
                status = getattr(getattr(e, "response", None), "status_code", None)
                if status in (404, 410):   # 만료된 기기 등록 제거
                    db.delete(sub)
            except Exception:
                pass
        db.commit()
    finally:
        db.close()
