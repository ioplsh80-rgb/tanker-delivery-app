"""기존 계근표·대화 사진의 드라이브 이름과 위치 정리 (1회성, 이어서 실행 가능).

예전에는 기사 휴대폰이 준 이름(IMG_2847.jpg 등)으로 저장되어 어느 배송건의
사진인지 알 수 없었다. 이것을 알아볼 수 있는 이름으로 바꾸고 폴더로 나눈다.

  계근표 → 완료/고객사/     D042_김정우_하이닉스(이천)_20260824_0915_황산_1.jpg
  대화   → 대화/고객사/     D042_김정우_하이닉스(이천)_20260824_091534_대화.jpg

- 한 장 처리할 때마다 drive_renamed 를 표시하므로, 중간에 멈춰도 다음 배포에서
  남은 것부터 이어서 진행한다. 전부 끝나면 드라이브 요청을 하나도 보내지 않는다.
- 서버 기동을 막지 않도록 앱이 뜬 뒤 별도 스레드에서 천천히 돌린다.
- 원본 파일 이름은 DB(delivery_photos.filename)에 그대로 남아 있다.
"""
import threading
import time
from datetime import timezone

import models
from database import SessionLocal

BATCH_SIZE = 50          # 한 번에 가져올 사진 수
SLEEP_BETWEEN = 0.15     # 드라이브 API를 몰아치지 않도록 사진 사이 간격(초)


def _to_kst(dt, KST):
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc).astimezone(KST) if dt.tzinfo is None else dt.astimezone(KST)


def _photo_seq_map(db, delivery_id: int):
    """같은 배송·같은 회차 안에서 몇 번째 사진인지 (등록 순서 기준)."""
    rows = (db.query(models.DeliveryPhoto)
            .filter(models.DeliveryPhoto.delivery_id == delivery_id)
            .order_by(models.DeliveryPhoto.id)
            .all())
    seq, counter = {}, {}
    for p in rows:
        b = p.batch_no or 1
        counter[b] = counter.get(b, 0) + 1
        seq[p.id] = counter[b]
    return seq


def _apply(service, file_id: str, new_name: str, target_folder: str, parents):
    old_parents = ",".join(parents or [])
    params = {"fileId": file_id, "body": {"name": new_name},
              "addParents": target_folder, "fields": "id"}
    if old_parents and old_parents != target_folder:
        params["removeParents"] = old_parents
    service.files().update(**params).execute()


def _run():
    from routers.deliveries import (KST, chat_photo_folders, chat_photo_name,
                                    get_drive_service, resolve_drive_folder,
                                    weighing_photo_folders, weighing_photo_name)

    service = get_drive_service()
    if not service:
        print("[드라이브 정리] 드라이브 연결 없음 - 건너뜀")
        return

    folder_cache = {}
    done = failed = 0

    def target_folder(company, kind):
        key = (kind, company or "")
        if key not in folder_cache:
            names = (weighing_photo_folders(company) if kind == "계근표"
                     else chat_photo_folders(company))
            folder_cache[key] = resolve_drive_folder(service, names)
        return folder_cache[key]

    def process(model, kind):
        """kind: '계근표' | '대화'. 남은 것이 없을 때까지 돌린다."""
        nonlocal done, failed
        while True:
            db = SessionLocal()
            try:
                rows = (db.query(model)
                        .filter(model.drive_file_id.isnot(None),
                                model.drive_file_id != "",
                                model.drive_renamed.isnot(True))
                        .order_by(model.id)
                        .limit(BATCH_SIZE)
                        .all())
                if not rows:
                    return True

                progressed = False
                seq_cache = {}
                for r in rows:
                    try:
                        d = (db.query(models.Delivery)
                             .filter(models.Delivery.id == r.delivery_id).first())
                        if not d:
                            r.drive_renamed = True   # 카드가 없으면 손댈 근거가 없다
                            progressed = True
                            continue

                        # 확장자는 드라이브에 있는 현재 이름에서 가져온다
                        # (대화 사진은 원본 이름을 DB에 두지 않는다)
                        meta = service.files().get(
                            fileId=r.drive_file_id, fields="name,parents").execute()
                        current_name = meta.get("name")

                        if kind == "계근표":
                            if d.id not in seq_cache:
                                seq_cache[d.id] = _photo_seq_map(db, d.id)
                            when = _to_kst(r.uploaded_at, KST) or _to_kst(d.created_at, KST)
                            new_name = weighing_photo_name(
                                d, when, r.batch_no or 1, seq_cache[d.id].get(r.id, 1),
                                current_name or r.filename)
                        else:
                            when = _to_kst(r.created_at, KST) or _to_kst(d.created_at, KST)
                            uploader = r.user.name if r.user else None
                            new_name = chat_photo_name(d, uploader, when, current_name)

                        folder = target_folder(d.company, kind)
                        if not folder:
                            print("[드라이브 정리] 대상 폴더를 만들 수 없음 - 중단")
                            return False

                        _apply(service, r.drive_file_id, new_name, folder, meta.get("parents"))
                        r.drive_renamed = True
                        done += 1
                        progressed = True
                    except Exception as e:
                        # 한 장이 실패해도 나머지는 계속한다.
                        # 표시를 남기지 않으므로 다음 배포에서 다시 시도한다.
                        failed += 1
                        print(f"[드라이브 정리] {kind} {r.id} 실패: {type(e).__name__} {e}")
                    time.sleep(SLEEP_BETWEEN)

                db.commit()
                if not progressed:
                    print(f"[드라이브 정리] {kind} 진전이 없어 중단합니다")
                    return False
            except Exception as e:
                db.rollback()
                print(f"[드라이브 정리] {kind} 중단: {type(e).__name__} {e}")
                return False
            finally:
                db.close()

    process(models.DeliveryPhoto, "계근표")
    process(models.DeliveryMessage, "대화")
    if done or failed:
        print(f"[드라이브 정리] 완료 - 정리 {done}건, 실패 {failed}건")


def start_background():
    """앱 기동 후 호출. 남은 사진이 없으면 곧바로 끝난다."""
    t = threading.Thread(target=_run, name="drive-cleanup", daemon=True)
    t.start()
