from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
import models
from database import engine
from routers import auth, deliveries, users, exports, vehicles, items, companies

# DB 테이블 생성
models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="탱크로리 배송 관리 시스템", version="1.0.0", redirect_slashes=False)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API 라우터 등록
app.include_router(auth.router,       prefix="/api/auth",      tags=["인증"])
app.include_router(users.router,      prefix="/api/users",     tags=["사용자"])
app.include_router(deliveries.router, prefix="/api/deliveries",tags=["배송"])
app.include_router(exports.router,    prefix="/api/exports",   tags=["내보내기"])
app.include_router(vehicles.router,   prefix="/api/vehicles",  tags=["차량"])
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
