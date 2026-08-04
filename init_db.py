"""
초기 데이터 생성 스크립트
실행: python init_db.py
"""
from datetime import datetime

import models
from database import SessionLocal, engine
from routers.auth import get_password_hash
from sqlalchemy import text

# 테이블 생성
models.Base.metadata.create_all(bind=engine)

# ── DB 컬럼 마이그레이션 (새 컬럼이 없으면 추가) ──────────────────
print("DB 마이그레이션 확인 중...")
migrations = [
    # users 테이블
    ("users", "department",         "VARCHAR(100)"),
    ("users", "email",              "VARCHAR(200)"),
    ("users", "phone",              "VARCHAR(50)"),
    ("users", "can_create_delivery","BOOLEAN DEFAULT FALSE"),
    ("users", "can_assign_vehicle", "BOOLEAN DEFAULT FALSE"),
    ("users", "vehicle_id",         "INTEGER"),
    ("users", "vehicle_number",     "VARCHAR(20)"),
    ("users", "vehicle_type",       "VARCHAR(50)"),
    ("users", "token_valid_from",   "TIMESTAMP"),
    # companies 테이블
    ("companies", "contact_name",   "VARCHAR(100)"),
    ("companies", "contact_email",  "VARCHAR(200)"),
    ("companies", "contact_phone",  "VARCHAR(50)"),
    # deliveries 테이블
    ("deliveries", "delivery_type", "VARCHAR(10) DEFAULT '출하'"),
    ("deliveries", "driving_time",  "VARCHAR(5)"),
    ("deliveries", "unloaded_time", "VARCHAR(5)"),
    ("deliveries", "is_deleted",    "BOOLEAN DEFAULT FALSE"),
    ("deliveries", "work_start_time", "VARCHAR(5)"),
    ("deliveries", "weighed_time",  "VARCHAR(5)"),
    ("deliveries", "assigned_by",   "INTEGER"),
    ("delivery_notice_acks", "stage", "VARCHAR(10)"),
    # delivery_photos 테이블
    ("delivery_photos", "drive_file_id", "VARCHAR(200)"),
]

with engine.connect() as conn:
    db_url = str(engine.url)
    is_pg = db_url.startswith("postgresql")
    for table, column, col_type in migrations:
        try:
            if is_pg:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {col_type}"))
            else:
                # SQLite: IF NOT EXISTS 미지원, 오류 무시
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"))
            conn.commit()
        except Exception:
            conn.rollback()
print("✅ 마이그레이션 완료")

# ── 배송 단계 개편: 구 상태값(driving) → 새 통합 흐름으로 변환 (1회성, 멱등) ──
with engine.connect() as conn:
    try:
        # 출하의 운행중(상차 후)은 '상차'로, 입하의 운행중(상차 전)은 '업무시작'으로
        conn.execute(text("UPDATE deliveries SET status='loaded' WHERE status='driving' AND delivery_type='출하'"))
        conn.execute(text("UPDATE deliveries SET status='start' WHERE status='driving' AND delivery_type!='출하'"))
        conn.commit()
        print("✅ 배송 단계 상태값 변환 완료")
    except Exception as e:
        conn.rollback()
        print(f"⚠️ 상태값 변환 건너뜀: {e}")

db = SessionLocal()

# ── 사용자 ──────────────────────────────────────────────
if db.query(models.User).count() == 0:
    print("초기 사용자 데이터를 생성합니다...")
    seed_users = [
        # 슈퍼관리자 1명 (모든 권한)
        {"name": "슈퍼관리자", "username": "superadmin", "password": "Super1234!", "role": "superadmin",
         "can_create_delivery": True, "can_assign_vehicle": True},
        # 관리자 15명 (두 권한 모두 부여)
        *[
            {"name": f"관리자{i:02d}", "username": f"admin{i:02d}",
             "password": "Admin1234!", "role": "admin",
             "can_create_delivery": True, "can_assign_vehicle": True}
            for i in range(1, 16)
        ],
        # 기사는 '기사 관리' 탭에서 별도 추가 (seed 데이터 없음)
    ]
    for u in seed_users:
        db.add(models.User(
            name=u["name"],
            username=u["username"],
            password_hash=get_password_hash(u["password"]),
            role=u["role"],
            can_create_delivery=u.get("can_create_delivery", False),
            can_assign_vehicle=u.get("can_assign_vehicle", False),
        ))
    db.commit()
    print(f"  사용자 {len(seed_users)}명 생성 완료")
    print("   슈퍼관리자: superadmin / 비밀번호: Super1234!")
    print("   관리자: admin01~admin15 / 비밀번호: Admin1234!")
else:
    print("ℹ️  사용자 데이터가 이미 존재합니다. 건너뜁니다.")

# ── 차량 ──────────────────────────────────────────────
if db.query(models.Vehicle).count() == 0:
    print("초기 차량 데이터를 생성합니다...")
    seed_vehicles = [
        {"vehicle_number": "12가 3456", "vehicle_type": "탱크로리 20톤", "capacity": 20000},
        {"vehicle_number": "34나 7890", "vehicle_type": "탱크로리 15톤", "capacity": 15000},
        {"vehicle_number": "56다 1234", "vehicle_type": "탱크로리 20톤", "capacity": 20000},
        {"vehicle_number": "78라 5678", "vehicle_type": "탱크로리 10톤", "capacity": 10000},
        {"vehicle_number": "90마 9012", "vehicle_type": "탱크로리 15톤", "capacity": 15000},
    ]
    for v in seed_vehicles:
        db.add(models.Vehicle(**v))
    db.commit()
    print(f"✅ 차량 {len(seed_vehicles)}대 생성 완료")
else:
    print("ℹ️  차량 데이터가 이미 존재합니다. 건너뜁니다.")

# ── 품목 ──────────────────────────────────────────────
if db.query(models.Item).count() == 0:
    print("초기 품목 데이터를 생성합니다...")
    seed_items = [
        "황산 (H₂SO₄)",
        "염산 (HCl)",
        "질산 (HNO₃)",
        "수산화나트륨 (NaOH)",
        "암모니아수 (NH₃)",
        "과산화수소 (H₂O₂)",
        "톨루엔",
        "메탄올",
        "에탄올",
    ]
    for name in seed_items:
        db.add(models.Item(name=name))
    db.commit()
    print(f"✅ 품목 {len(seed_items)}개 생성 완료")
else:
    print("ℹ️  품목 데이터가 이미 존재합니다. 건너뜁니다.")

# ── 고객사 ──────────────────────────────────────────────
if db.query(models.Company).count() == 0:
    print("초기 고객사 데이터를 생성합니다...")
    seed_companies = [
        {"name": "한화케미칼", "address": "서울시 중구"},
        {"name": "LG화학", "address": "서울시 영등포구"},
        {"name": "롯데케미칼", "address": "서울시 송파구"},
        {"name": "SK이노베이션", "address": "서울시 종로구"},
        {"name": "금호석유화학", "address": "서울시 강남구"},
    ]
    for c in seed_companies:
        db.add(models.Company(name=c["name"], address=c["address"]))
    db.commit()
    print(f"✅ 고객사 {len(seed_companies)}개 생성 완료")
else:
    print("ℹ️  고객사 데이터가 이미 존재합니다. 건너뜁니다.")

# ── [1회성] 고객사 주의사항을 '하이닉스(이천)' 것으로 통일 ────────────
# 활성 고객사 전체의 기존 주의사항을 지우고 원본 고객사의 주의사항으로 맞춘다.
# 원본 고객사 자신은 건드리지 않는다.
# 삭제분은 company_notices_backup 에 백업하고, oneoff_flags 로 1회만 실행한다.
# ※ 실행 확인 후 다음 배포 때 이 블록을 제거할 것.
SRC_COMPANY_NAME = "하이닉스(이천)"
UNIFY_FLAG_KEY = "unify_company_notices_20260804"


def unify_company_notices():
    conn = db.connection()

    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS oneoff_flags (
            flag_key VARCHAR(100) PRIMARY KEY,
            done_at TIMESTAMP
        )
    """))
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS company_notices_backup (
            notice_id     INTEGER,
            company_id    INTEGER,
            company_name  VARCHAR(100),
            content       TEXT,
            drive_file_id VARCHAR(200),
            order_num     INTEGER,
            backed_up_at  TIMESTAMP
        )
    """))

    done = conn.execute(
        text("SELECT 1 FROM oneoff_flags WHERE flag_key = :k"),
        {"k": UNIFY_FLAG_KEY},
    ).first()
    if done:
        print("ℹ️  주의사항 통일: 이미 실행됨. 건너뜁니다.")
        return

    src = db.query(models.Company).filter(
        models.Company.name == SRC_COMPANY_NAME).first()
    if not src:
        print(f"⚠️  주의사항 통일 중단: 고객사 '{SRC_COMPANY_NAME}' 을(를) 찾지 못했습니다.")
        return

    src_notices = (
        db.query(models.CompanyNotice)
        .filter(models.CompanyNotice.company_id == src.id)
        .order_by(models.CompanyNotice.order_num, models.CompanyNotice.id)
        .all()
    )
    if not src_notices:
        print(f"⚠️  주의사항 통일 중단: '{SRC_COMPANY_NAME}' 에 등록된 주의사항이 없습니다.")
        return

    template = [(n.content, n.drive_file_id) for n in src_notices]
    print(f"📋 원본 '{SRC_COMPANY_NAME}' 주의사항 {len(template)}개를 복사합니다.")

    # 되돌릴 수 있도록 현재 주의사항 전체를 백업 (원본 포함)
    now = datetime.utcnow()
    all_notices = db.query(models.CompanyNotice).all()
    id_to_name = {c.id: c.name for c in db.query(models.Company).all()}
    for n in all_notices:
        conn.execute(
            text("""
                INSERT INTO company_notices_backup
                    (notice_id, company_id, company_name, content,
                     drive_file_id, order_num, backed_up_at)
                VALUES (:nid, :cid, :cname, :content, :fid, :onum, :ts)
            """),
            {"nid": n.id, "cid": n.company_id,
             "cname": id_to_name.get(n.company_id), "content": n.content,
             "fid": n.drive_file_id, "onum": n.order_num, "ts": now},
        )
    print(f"💾 기존 주의사항 {len(all_notices)}건을 company_notices_backup 에 백업했습니다.")

    targets = (
        db.query(models.Company)
        .filter(models.Company.is_active == True, models.Company.id != src.id)
        .order_by(models.Company.name)
        .all()
    )

    removed = 0
    for c in targets:
        removed += (
            db.query(models.CompanyNotice)
            .filter(models.CompanyNotice.company_id == c.id)
            .delete(synchronize_session=False)
        )
        for i, (content, fid) in enumerate(template):
            db.add(models.CompanyNotice(
                company_id=c.id, content=content,
                drive_file_id=fid, order_num=i,
            ))

    conn.execute(
        text("INSERT INTO oneoff_flags (flag_key, done_at) VALUES (:k, :ts)"),
        {"k": UNIFY_FLAG_KEY, "ts": now},
    )
    db.commit()
    print(f"✅ 활성 고객사 {len(targets)}곳에 주의사항 {len(template)}개씩 적용 "
          f"(기존 {removed}건 삭제, 원본 '{SRC_COMPANY_NAME}' 제외)")


try:
    unify_company_notices()
except Exception as e:
    # 이 스크립트가 실패해도 서버 기동은 막지 않는다
    db.rollback()
    print(f"⚠️ 주의사항 통일 건너뜀: {e}")

db.close()
print("\n✅ 초기화 완료!")
