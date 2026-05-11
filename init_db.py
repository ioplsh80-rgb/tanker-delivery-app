"""
초기 데이터 생성 스크립트
실행: python init_db.py
"""
import models
from database import SessionLocal, engine
from routers.auth import get_password_hash

# 테이블 생성
models.Base.metadata.create_all(bind=engine)

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
        # 배송기사 10명 (차량은 배송 할당 시 별도 지정)
        {"name": "박민준", "username": "driver01", "password": "Driver1234!", "role": "driver"},
        {"name": "최성호", "username": "driver02", "password": "Driver1234!", "role": "driver"},
        {"name": "정동혁", "username": "driver03", "password": "Driver1234!", "role": "driver"},
        {"name": "이재원", "username": "driver04", "password": "Driver1234!", "role": "driver"},
        {"name": "김태호", "username": "driver05", "password": "Driver1234!", "role": "driver"},
        {"name": "윤성민", "username": "driver06", "password": "Driver1234!", "role": "driver"},
        {"name": "한동훈", "username": "driver07", "password": "Driver1234!", "role": "driver"},
        {"name": "조현우", "username": "driver08", "password": "Driver1234!", "role": "driver"},
        {"name": "서진수", "username": "driver09", "password": "Driver1234!", "role": "driver"},
        {"name": "남궁민", "username": "driver10", "password": "Driver1234!", "role": "driver"},
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
    print(f"✅ 사용자 {len(seed_users)}명 생성 완료")
    print("   슈퍼관리자: superadmin / 비밀번호: Super1234!")
    print("   관리자: admin01~admin15 / 비밀번호: Admin1234!")
    print("   기사:   driver01~driver10 / 비밀번호: Driver1234!")
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
