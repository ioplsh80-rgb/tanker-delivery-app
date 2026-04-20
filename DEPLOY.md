# Railway 배포 가이드

## 1단계 — GitHub 저장소 만들기

```bash
cd tanker-delivery-app
git init
git add .
git commit -m "초기 배포"
```

GitHub에서 새 저장소 만들고 push:
```bash
git remote add origin https://github.com/your-id/tanker-delivery.git
git push -u origin main
```

---

## 2단계 — Railway에서 프로젝트 생성

1. https://railway.app 접속 → 로그인
2. **New Project** 클릭
3. **Deploy from GitHub repo** 선택 → 저장소 선택

---

## 3단계 — PostgreSQL 데이터베이스 추가

1. 프로젝트 대시보드에서 **New** 클릭
2. **Database → Add PostgreSQL** 선택
3. 생성 완료 후 **Variables 탭**에서 `DATABASE_URL` 확인

---

## 4단계 — 환경 변수 설정

앱 서비스 선택 → **Variables 탭**에서 추가:

| 변수명 | 값 |
|--------|-----|
| `DATABASE_URL` | PostgreSQL 서비스의 DATABASE_URL (자동 연결) |
| `SECRET_KEY` | 임의의 긴 문자열 (예: `mySecretKey2024!@#`) |

> Railway에서 PostgreSQL을 같은 프로젝트에 추가하면 `DATABASE_URL`이 자동으로 연결됩니다.

---

## 5단계 — 배포 확인

1. **Deployments 탭**에서 배포 로그 확인
2. 배포 완료 후 **Settings → Domains**에서 URL 복사
3. 브라우저에서 접속 테스트

---

## 초기 계정

| 구분 | 아이디 | 비밀번호 |
|------|--------|---------|
| 관리자 | admin01 ~ admin15 | Admin1234! |
| 기사 | driver01 ~ driver10 | Driver1234! |

> 배포 후 반드시 비밀번호를 변경하세요.

---

## 문제 해결

- **502 오류**: Railway 로그에서 에러 확인 → `DATABASE_URL` 환경 변수 설정 여부 점검
- **사진 업로드 느림**: 사진 용량이 크면 업로드 시간이 길어질 수 있음 (압축 권장)
