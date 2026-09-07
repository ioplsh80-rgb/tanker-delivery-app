"""푸시 알림.

- 브라우저(설치된 PWA 포함)의 푸시 구독을 등록하고,
- 배송 이벤트 발생 시 대상 사용자의 모든 기기로 알림을 발송한다.
- VAPID 비밀키(VAPID_PRIVATE_KEY)가 환경변수에 없으면 발송은 조용히 건너뜀.
"""
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

KST = timezone(timedelta(hours=9))

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import or_
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


@router.post("/test")
def test_push(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """본인 기기로 테스트 알림을 즉시 발송하고 기기별 상세 결과 반환 (진단용)"""
    subs = db.query(models.PushSubscription).filter(
        models.PushSubscription.user_id == current_user.id).all()
    private_key = (os.getenv("VAPID_PRIVATE_KEY") or "").strip()
    vapid_ok = bool(private_key)
    try:
        from pywebpush import webpush, WebPushException
        lib_ok = True
    except ImportError:
        lib_ok = False

    # 키 자체가 유효한지 미리 검사 (값은 노출하지 않고 길이만 반환)
    key_valid = False
    if private_key and lib_ok:
        try:
            from py_vapid import Vapid01
            Vapid01.from_string(private_key)
            key_valid = True
        except Exception:
            key_valid = False

    results = []
    if subs and vapid_ok and lib_ok and key_valid:
        payload = json.dumps({
            "title": "🔔 테스트 알림",
            "body": f"{current_user.name}님, 알림이 정상 작동합니다!",
            "url": "/", "badge": 1,
        }, ensure_ascii=False)
        for sub in subs:
            try:
                webpush(
                    subscription_info=json.loads(sub.subscription_json),
                    data=payload,
                    vapid_private_key=private_key,
                    vapid_claims=dict(VAPID_CLAIMS),
                )
                results.append("성공")
            except WebPushException as e:
                status = getattr(getattr(e, "response", None), "status_code", None)
                body = ""
                try:
                    body = e.response.text[:150] if e.response is not None else ""
                except Exception:
                    pass
                results.append(f"실패({status}): {body or str(e)[:150]}")
            except Exception as e:
                results.append(f"오류({type(e).__name__}): {str(e)[:150]}")
    return {"devices": len(subs), "vapid_configured": vapid_ok,
            "library_ok": lib_ok, "results": results,
            "key_length": len(private_key), "key_valid": key_valid}


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


def _unread_message_count(db: Session, user_id: int) -> int:
    """앱 아이콘 뱃지용: 이 사용자의 안 읽은 대화 메시지 총 개수."""
    ids = [r[0] for r in db.query(models.Delivery.id).filter(
        models.Delivery.is_deleted.is_not(True),
        or_(
            models.Delivery.driver_id == user_id,
            models.Delivery.created_by == user_id,
            models.Delivery.assigned_by == user_id,
        ),
    ).all()]
    if not ids:
        return 0
    reads = {
        r.delivery_id: r.last_read_at
        for r in db.query(models.DeliveryMessageRead).filter(
            models.DeliveryMessageRead.user_id == user_id,
            models.DeliveryMessageRead.delivery_id.in_(ids),
        ).all()
    }
    msgs = db.query(models.DeliveryMessage).filter(
        models.DeliveryMessage.delivery_id.in_(ids),
        models.DeliveryMessage.user_id != user_id,
    ).all()
    count = 0
    for m in msgs:
        last_read = reads.get(m.delivery_id)
        if last_read is None or m.created_at > last_read:
            count += 1
    return count


def send_push_to_users(user_ids, title: str, message: str, url: str = "/"):
    """대상 사용자들의 모든 기기로 푸시 발송 (백그라운드 작업용).
    수신자별 안 읽은 개수를 뱃지 숫자로 포함. 만료된 구독은 자동 정리."""
    if not user_ids:
        return
    private_key = os.getenv("VAPID_PRIVATE_KEY")
    try:
        from pywebpush import webpush, WebPushException
        lib_ok = True
    except ImportError:
        lib_ok = False

    if not private_key or not lib_ok:
        # 이 경우 아무에게도 안 간다. 조용히 넘어가면 원인을 찾을 수 없어 남긴다.
        reason = "서버에 알림 키(VAPID)가 없음" if not private_key else "서버에 알림 모듈 없음"
        db = SessionLocal()
        try:
            for uid in set(user_ids):
                if uid is None:
                    continue
                db.add(models.PushLog(user_id=uid, title=title, body=message,
                                      endpoint="", ok=False, detail=reason))
            db.commit()
        except Exception:
            db.rollback()
        finally:
            db.close()
        return

    db = SessionLocal()

    def log(uid, endpoint, ok, detail):
        # 발송 결과를 남긴다. 이게 없으면 '알림이 안 왔다'는 말을 확인할 방법이 없다.
        db.add(models.PushLog(
            user_id=uid, title=title, body=message,
            endpoint=(endpoint or "")[:500], ok=ok, detail=detail[:300]))

    try:
        for uid in set(user_ids):
            if uid is None:
                continue
            subs = db.query(models.PushSubscription).filter(
                models.PushSubscription.user_id == uid).all()
            if not subs:
                # 가장 흔한 원인. 알림을 켠 적이 없거나 등록이 만료돼 지워진 상태다.
                log(uid, None, False, "기기 등록 없음 (앱에서 알림 켜기 필요)")
                continue
            badge = min(_unread_message_count(db, uid) or 1, 99)  # 최소 1 (확인할 알림 존재)
            payload = json.dumps(
                {"title": title, "body": message, "url": url, "badge": badge},
                ensure_ascii=False)
            for sub in subs:
                try:
                    webpush(
                        subscription_info=json.loads(sub.subscription_json),
                        data=payload,
                        vapid_private_key=private_key,
                        vapid_claims=dict(VAPID_CLAIMS),
                    )
                    log(uid, sub.endpoint, True, "성공")
                except WebPushException as e:
                    status = getattr(getattr(e, "response", None), "status_code", None)
                    if status in (404, 410):   # 만료된 기기 등록 제거
                        db.delete(sub)
                        log(uid, sub.endpoint, False,
                            f"기기 등록 만료({status}) — 등록을 지웠다. 앱을 열면 다시 등록된다")
                    else:
                        log(uid, sub.endpoint, False, f"발송 실패({status}): {str(e)[:150]}")
                except Exception as e:
                    log(uid, sub.endpoint, False, f"{type(e).__name__}: {str(e)[:150]}")
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()


# ── 발송 기록 조회 (진단용) ────────────────────────────────────────────────
@router.get("/logs")
def push_logs(
    limit: int = 200,
    only_failed: bool = False,
    user_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """알림이 실제로 나갔는지 확인하는 기록. 슈퍼관리자만."""
    if current_user.role != "superadmin":
        raise HTTPException(status_code=403, detail="슈퍼관리자만 볼 수 있습니다.")

    q = db.query(models.PushLog)
    if only_failed:
        q = q.filter(models.PushLog.ok == False)   # noqa: E712
    if user_id:
        q = q.filter(models.PushLog.user_id == user_id)
    # 시각 기준 최신순 (id 만으로는 기록을 옮겨 넣은 경우 순서가 어긋날 수 있다)
    rows = q.order_by(models.PushLog.created_at.desc(), models.PushLog.id.desc()).limit(min(limit, 500)).all()

    # 최근 24시간 요약 — 자잘한 기록을 다 보기 전에 상태를 한눈에
    since = datetime.utcnow() - timedelta(hours=24)
    recent = db.query(models.PushLog).filter(models.PushLog.created_at >= since).all()
    ok_cnt = sum(1 for r in recent if r.ok)

    # 실패가 잦은 사람을 짚어준다
    by_user = {}
    for r in recent:
        if r.ok or not r.user_id:
            continue
        by_user[r.user_id] = by_user.get(r.user_id, 0) + 1
    names = {}
    if by_user:
        for u in db.query(models.User).filter(models.User.id.in_(by_user.keys())).all():
            names[u.id] = u.name

    return {
        "summary": {
            "recent_total": len(recent),
            "recent_ok": ok_cnt,
            "recent_failed": len(recent) - ok_cnt,
            "failed_by_user": sorted(
                ({"name": names.get(uid, f"#{uid}"), "count": c} for uid, c in by_user.items()),
                key=lambda x: -x["count"]),
        },
        "logs": [{
            "id": r.id,
            "user_name": r.user.name if r.user else "",
            "title": r.title,
            "ok": r.ok,
            "detail": r.detail,
            "device": (r.endpoint or "")[:60],
            "created_at": (r.created_at.replace(tzinfo=timezone.utc).astimezone(KST).strftime("%m-%d %H:%M")
                           if r.created_at else ""),
        } for r in rows],
    }
