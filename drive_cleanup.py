"""기존 계근표 사진의 드라이브 이름·위치 정리 (1회성, 이어서 실행 가능).

예전에는 기사 휴대폰이 준 이름(IMG_2847.jpg 등)으로 기본 폴더에 그대로 쌓였다.
이것을 '완료/고객사/' 폴더 아래로 옮기고, 알아볼 수 있는 이름으로 바꾼다.

- 사진 한 장을 처리할 때마다 delivery_photos.drive_renamed 를 표시하므로,
  중간에 멈춰도 다음 배포에서 남은 것부터 이어서 진행한다.
- 서버 기동을 막지 않도록 앱이 뜬 뒤 별도 스레드에서 천천히 돌린다.
- 원본 파일 이름은 delivery_photos.filename 에 그대로 남아 있어 되돌릴 수 있다.
"""
import threading
import time
from datetime import timezone

import models
from database import SessionLocal

BATCH_SIZE = 50          # 한 번에 가져올 사진 수
SLEEP_BETWEEN = 0.15     # 드라이브 API를 몰아치지 않도록 사진 사이 간격(초)


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


def _run():
    from routers.deliveries import (KST, get_drive_service, resolve_drive_folder,
                                    weighing_photo_folders, weighing_photo_name)

    service = get_drive_service()
    if not service:
        print("[드라이브 정리] 드라이브 연결 없음 - 건너뜀")
        return

    folder_cache = {}
    done = failed = 0

    while True:
        db = SessionLocal()
        try:
            photos = (db.query(models.DeliveryPhoto)
                      .filter(models.DeliveryPhoto.drive_file_id.isnot(None),
                              models.DeliveryPhoto.drive_file_id != "",
                              models.DeliveryPhoto.drive_renamed.isnot(True))
                      .order_by(models.DeliveryPhoto.id)
                      .limit(BATCH_SIZE)
                      .all())
            if not photos:
                break

            seq_cache = {}
            for p in photos:
                try:
                    d = (db.query(models.Delivery)
                         .filter(models.Delivery.id == p.delivery_id).first())
                    if not d:
                        p.drive_renamed = True   # 카드가 없으면 손댈 근거가 없다
                        continue

                    if d.id not in seq_cache:
                        seq_cache[d.id] = _photo_seq_map(db, d.id)
                    seq = seq_cache[d.id].get(p.id, 1)

                    uploaded = p.uploaded_at
                    uploaded_kst = (uploaded.replace(tzinfo=timezone.utc).astimezone(KST)
                                    if uploaded else d.updated_at or d.created_at)
                    if uploaded_kst.tzinfo is None:
                        uploaded_kst = uploaded_kst.replace(tzinfo=timezone.utc).astimezone(KST)

                    new_name = weighing_photo_name(d, uploaded_kst, p.batch_no or 1, seq, p.filename)

                    company_key = d.company or ""
                    if company_key not in folder_cache:
                        folder_cache[company_key] = resolve_drive_folder(
                            service, weighing_photo_folders(d.company))
                    target = folder_cache[company_key]
                    if not target:
                        print("[드라이브 정리] 대상 폴더를 만들 수 없음 - 중단")
                        return

                    meta = service.files().get(fileId=p.drive_file_id,
                                               fields="parents").execute()
                    old_parents = ",".join(meta.get("parents", []))
                    params = {"fileId": p.drive_file_id, "body": {"name": new_name},
                              "addParents": target, "fields": "id"}
                    if old_parents and old_parents != target:
                        params["removeParents"] = old_parents
                    service.files().update(**params).execute()

                    p.drive_renamed = True
                    done += 1
                except Exception as e:
                    # 파일 하나가 실패해도 나머지는 계속한다.
                    # 표시를 남기지 않으므로 다음 배포에서 다시 시도한다.
                    failed += 1
                    print(f"[드라이브 정리] 사진 {p.id} 실패: {type(e).__name__} {e}")
                time.sleep(SLEEP_BETWEEN)

            db.commit()
        except Exception as e:
            db.rollback()
            print(f"[드라이브 정리] 중단: {type(e).__name__} {e}")
            return
        finally:
            db.close()

        if failed and done == 0:
            print("[드라이브 정리] 진전이 없어 중단합니다")
            return

    print(f"[드라이브 정리] 완료 - 정리 {done}건, 실패 {failed}건")


def start_background():
    """앱 기동 후 호출. 남은 사진이 없으면 곧바로 끝난다."""
    t = threading.Thread(target=_run, name="drive-cleanup", daemon=True)
    t.start()
