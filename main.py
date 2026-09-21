from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.encoders import jsonable_encoder
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import models
from database import engine
from routers import (auth, deliveries, users, exports, items, companies,
                     photos, push, stage_notices)

# DB 테이블 생성
models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="탱크로리 배송 관리 시스템", version="1.0.0", redirect_slashes=False)


# 사진 첨부가 잘못 전달됐을 때 알아들을 수 있게 알려준다.
# 휴대폰에서 사진을 고른 뒤 시간이 지나면 원본이 정리되어, 이름 없는 빈 조각이
# 전송된다. 그러면 서버는 파일이 아닌 글자로 받아 422로 거절하는데, 기본 문구가
# 영어 기술 용어라 기사에게는 '업로드 실패' 로만 보였다.
@app.exception_handler(RequestValidationError)
async def _validation_error(request: Request, exc: RequestValidationError):
    errors = exc.errors()
    if any("file" in str(e.get("loc", "")).lower() for e in errors):
        msg = ("사진을 다시 첨부해주세요. 사진을 고른 뒤 시간이 지나 "
               "휴대폰이 사진을 놓친 것 같습니다. (사진을 빼고 다시 첨부해주세요)")
    else:
        msg = "입력한 내용을 확인해주세요."
    return JSONResponse(status_code=422, content={"detail": msg, "errors": jsonable_encoder(errors)})

# 쿠키 인증 사용으로 출처를 자체 도메인으로 제한 (와일드카드 + 쿠키 조합은 위험)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://web-production-39d95.up.railway.app"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API 라우터 등록
app.include_router(auth.router,       prefix="/api/auth",      tags=["인증"])
app.include_router(users.router,      prefix="/api/users",     tags=["사용자"])
app.include_router(deliveries.router, prefix="/api/deliveries",tags=["배송"])
app.include_router(exports.router,    prefix="/api/exports",   tags=["내보내기"])
app.include_router(items.router,      prefix="/api/items",     tags=["품목"])
app.include_router(companies.router,  prefix="/api/companies", tags=["고객사"])
app.include_router(photos.router,     prefix="/api/photos",    tags=["사진"])
app.include_router(push.router,       prefix="/api/push",      tags=["알림"])
app.include_router(stage_notices.router, prefix="/api/stage-notices", tags=["안전 유의사항"])

# 정적 파일 (프론트엔드)
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
async def root():
    return FileResponse("static/index.html")


@app.get("/sw.js")
async def service_worker():
    # 루트 경로에서 제공해야 서비스 워커의 범위가 사이트 전체가 됨
    return FileResponse("static/sw.js", media_type="application/javascript")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.on_event("startup")
def _start_drive_cleanup():
    """예전 방식으로 저장된 계근표 사진의 이름·폴더 정리를 뒤에서 이어서 진행.
    남은 것이 없으면 즉시 끝나며, 실패해도 서비스에는 영향을 주지 않는다."""
    try:
        import drive_cleanup
        drive_cleanup.start_background()
    except Exception as e:
        print(f"[드라이브 정리] 시작 실패: {type(e).__name__} {e}")
