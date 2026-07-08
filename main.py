from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
import models
from database import engine
from routers import auth, deliveries, users, exports, items, companies

# DB 테이블 생성
models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="탱크로리 배송 관리 시스템", version="1.0.0", redirect_slashes=False)

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

# 정적 파일 (프론트엔드)
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
async def root():
    return FileResponse("static/index.html")


@app.get("/health")
async def health():
    return {"status": "ok"}
