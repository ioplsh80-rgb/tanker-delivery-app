"""
초기 데이터 생성 스크립트
실행: python init_db.py
"""
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
    # companies 테이블
    ("companies", "contact_name",   "VARCHAR(100)"),
    ("companies", "contact_email",  "VARCHAR(200)"),
    ("companies", "contact_phone",  "VARCHAR(50)"),
    # deliveries 테이블
    ("deliveries", "delivery_type", "VARCHAR(10) DEFAULT '출하'"),
    ("deliveries", "driving_time",  "VARCHAR(5)"),
    ("deliveries", "unloaded_time", "VARCHAR(5)"),
    ("deliveries", "is_deleted",    "BOOLEAN DEFAULT FALSE"),
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

db.close()
print("\n✅ 초기화 완료!")
