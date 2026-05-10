# GESS Raw Material Intelligence - Backend Server

## 데이터 소스 구성

| 원자재 | 소스 | 상태 | 비고 |
|--------|------|------|------|
| 구리 (Cu) | Yahoo Finance `HG=F` | ✅ 무료 | LME 선물 연동 |
| 알루미늄 (Al) | Yahoo Finance `ALI=F` | ✅ 무료 | LME 선물 연동 |
| 탄산리튬 (Li) | SMM API | 🔑 유료 | [metal.com](https://www.metal.com) 계약 필요 |
| ↳ Fallback | Macrotrends 스크래핑 | ⚠️ 임시 | SMM 계약 전 사용 |
| SMM Battery Index | SMM API | 🔑 유료 | System/Cell /kWh |

## 빠른 시작

```bash
# 1. 의존성 설치
pip install -r requirements.txt

# 2. 환경변수 설정
cp .env.example .env
# .env 파일에서 SMM_API_KEY 입력

# 3. 서버 실행
python server.py
# → http://localhost:8000

# 4. API 확인
curl http://localhost:8000/api/prices
curl http://localhost:8000/api/health
```

## API 엔드포인트

| Method | Path | 설명 |
|--------|------|------|
| GET | `/api/prices` | 전체 원자재 가격 |
| GET | `/api/prices/li` | 탄산리튬만 |
| GET | `/api/prices/al` | 알루미늄만 |
| GET | `/api/prices/cu` | 구리만 |
| GET | `/api/prices/smm` | SMM Battery Index |
| GET | `/api/refresh` | 수동 즉시 갱신 |
| GET | `/api/health` | 서버 상태 확인 |

## SMM API 계약 방법

1. https://www.metal.com (상해비철금속망) 접속
2. 영업팀 문의: info@metal.com
3. 제품: `Lithium Carbonate 99.5%`, `Battery System/Cell Index`
4. API 키 발급 후 `.env`의 `SMM_API_KEY`에 입력

## 갱신 주기

- 자동: **1시간마다** (APScheduler)
- 수동: `GET /api/refresh` 호출
- 서버 시작 시: 즉시 1회 갱신

## 배포 옵션

```bash
# Docker
docker build -t gess-server .
docker run -p 8000:8000 --env-file .env gess-server

# 클라우드 (AWS EC2, GCP, Azure)
# → 대시보드 HTML의 API_BASE_URL을 서버 IP로 변경
```
