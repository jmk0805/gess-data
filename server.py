"""
GESS Raw Material Intelligence - Backend Server
================================================
FastAPI 기반 원자재 가격 수집 서버

데이터 소스:
  - 구리 (Cu)      : Yahoo Finance HG=F 선물 (무료, 실시간)
  - 알루미늄 (Al)  : Yahoo Finance ALI=F 선물 (무료, 실시간)
  - 탄산리튬 (Li)  : SMM API (유료) → 미연결시 Macrotrends 스크래핑 fallback
  - SMM Battery Index: SMM API (유료) → 미연결시 CATL/업계 공시 기반 추정

환경변수 (.env):
  SMM_API_KEY=your_smm_api_key_here   # SMM 계약 후 발급
  PORT=8000
  CORS_ORIGIN=*
"""

import os, json, asyncio, logging
from datetime import datetime, timezone
from typing import Optional
import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("GESS")

app = FastAPI(title="GESS Raw Material API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # 운영 환경에서는 대시보드 도메인으로 제한
    allow_methods=["GET"],
    allow_headers=["*"],
)

# ── 캐시 (스케줄러가 1시간마다 갱신) ──
CACHE: dict = {
    "li":  {"price": 19.46, "unit": "USD/kg",  "chg_pct": 0.80,  "source": "SMM(fallback)", "updated": None},
    "al":  {"price": 3538,  "unit": "USD/mt",  "chg_pct": -1.20, "source": "Yahoo Finance", "updated": None},
    "cu":  {"price": 12930, "unit": "USD/mt",  "chg_pct": 2.10,  "source": "Yahoo Finance", "updated": None},
    "smm": {
        "system": {"price": 82.6,  "unit": "USD/kWh", "chg_pct": -3.1, "source": "SMM(fallback)"},
        "cell":   {"price": 45.1,  "unit": "USD/kWh", "chg_pct": -3.6, "source": "SMM(fallback)"},
        "updated": None
    },
    "last_full_update": None,
    "status": "initializing"
}

SMM_API_KEY = os.getenv("SMM_API_KEY", "")  # 비어있으면 fallback 모드

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json,text/html,*/*",
}

# ═══════════════════════════════════════════════
# 1. Yahoo Finance - 구리 / 알루미늄 (무료, 실시간)
# ═══════════════════════════════════════════════
async def fetch_yahoo(ticker: str) -> Optional[dict]:
    """Yahoo Finance v8 비공식 API로 선물 가격 조회"""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
    params = {"interval": "1d", "range": "5d"}
    try:
        async with httpx.AsyncClient(timeout=15, headers=HEADERS) as client:
            r = await client.get(url, params=params)
            r.raise_for_status()
            data = r.json()
            result = data["chart"]["result"][0]
            meta = result["meta"]
            price = meta.get("regularMarketPrice") or meta.get("previousClose")
            prev  = meta.get("chartPreviousClose") or meta.get("previousClose")
            chg   = round((price - prev) / prev * 100, 2) if prev else 0.0
            return {"price": round(price, 2), "chg_pct": chg, "source": "Yahoo Finance"}
    except Exception as e:
        log.error(f"Yahoo fetch failed ({ticker}): {e}")
        return None

# ═══════════════════════════════════════════════
# 2. SMM API - 탄산리튬 / SMM Battery Index (유료)
# ═══════════════════════════════════════════════
async def fetch_smm_lithium() -> Optional[dict]:
    """
    SMM 공식 API (계약 필요)
    API 문서: https://www.metal.com/api
    엔드포인트 예시 (실제 계약 후 확인 필요):
      GET https://api.metal.com/v1/price?product=lithium-carbonate&currency=USD
    """
    if not SMM_API_KEY:
        log.warning("SMM_API_KEY 미설정 → lithium fallback 사용")
        return None
    try:
        url = "https://api.metal.com/v1/price"
        params = {"product": "lithium-carbonate", "currency": "USD", "unit": "kg"}
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(url, params=params, headers={"X-API-KEY": SMM_API_KEY})
            r.raise_for_status()
            d = r.json()
            # SMM 응답 구조에 따라 파싱 조정 필요
            price = d["data"]["price"]
            prev  = d["data"].get("prev_price", price)
            chg   = round((price - prev) / prev * 100, 2)
            return {"price": round(price, 2), "chg_pct": chg, "source": "SMM API"}
    except Exception as e:
        log.error(f"SMM lithium fetch failed: {e}")
        return None

async def fetch_smm_battery_index() -> Optional[dict]:
    """SMM Battery System/Cell Index (유료 API)"""
    if not SMM_API_KEY:
        return None
    try:
        url = "https://api.metal.com/v1/battery-index"
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(url, headers={"X-API-KEY": SMM_API_KEY})
            r.raise_for_status()
            d = r.json()
            return {
                "system": {"price": d["system_price"], "chg_pct": d["system_chg"], "source": "SMM API"},
                "cell":   {"price": d["cell_price"],   "chg_pct": d["cell_chg"],   "source": "SMM API"},
            }
    except Exception as e:
        log.error(f"SMM battery index fetch failed: {e}")
        return None

# ═══════════════════════════════════════════════
# 3. Fallback - 탄산리튬 Macrotrends 스크래핑
#    (SMM API 없을 때 / 월간 업데이트 수준)
# ═══════════════════════════════════════════════
async def fetch_lithium_fallback() -> Optional[dict]:
    """
    Macrotrends 리튬 가격 페이지 스크래핑 (fallback)
    - 일별 업데이트, USD/kg 기준
    - SMM 계약 전 임시 사용
    """
    url = "https://www.macrotrends.net/2441/lithium-price-history-chart"
    try:
        async with httpx.AsyncClient(timeout=20, headers=HEADERS, follow_redirects=True) as client:
            r = await client.get(url)
            r.raise_for_status()
            # 페이지 내 JSON 데이터 추출
            text = r.text
            start = text.find('"data":[[') 
            if start == -1:
                raise ValueError("Data not found in page")
            end = text.find("]]", start) + 2
            raw = text[start+8:end]
            rows = json.loads(raw)
            if len(rows) >= 2:
                latest = rows[-1][1]
                prev   = rows[-2][1]
                chg = round((latest - prev) / prev * 100, 2) if prev else 0.0
                return {"price": round(latest, 2), "chg_pct": chg, "source": "Macrotrends(fallback)"}
    except Exception as e:
        log.error(f"Lithium fallback scrape failed: {e}")
    return None

# ═══════════════════════════════════════════════
# 4. 메인 데이터 갱신 함수 (스케줄러 호출)
# ═══════════════════════════════════════════════
async def refresh_all():
    log.info("🔄 데이터 갱신 시작...")
    now = datetime.now(timezone.utc).isoformat()

    # 구리 (Yahoo Finance HG=F)
    cu = await fetch_yahoo("HG=F")
    if cu:
        # LME 기준으로 단위 환산: Yahoo HG=F는 USD/lb → USD/mt (*2204.62)
        cu["price"] = round(cu["price"] * 2204.62, 0)
        CACHE["cu"].update({**cu, "unit": "USD/mt", "updated": now})
        log.info(f"  ✅ Cu: ${CACHE['cu']['price']:,.0f}/mt ({cu['chg_pct']:+.2f}%)")
    else:
        log.warning("  ⚠️  Cu: Yahoo fallback 사용")

    # 알루미늄 (Yahoo Finance ALI=F)
    al = await fetch_yahoo("ALI=F")
    if al:
        # ALI=F는 USD/mt 기준 (LME와 동일)
        CACHE["al"].update({**al, "unit": "USD/mt", "updated": now})
        log.info(f"  ✅ Al: ${CACHE['al']['price']:,.0f}/mt ({al['chg_pct']:+.2f}%)")
    else:
        log.warning("  ⚠️  Al: Yahoo fallback 사용")

    # 탄산리튬 (SMM → Macrotrends fallback)
    li = await fetch_smm_lithium()
    if not li:
        li = await fetch_lithium_fallback()
    if li:
        CACHE["li"].update({**li, "unit": "USD/kg", "updated": now})
        log.info(f"  ✅ Li: ${CACHE['li']['price']}/kg ({li['chg_pct']:+.2f}%) [{li['source']}]")
    else:
        log.warning("  ⚠️  Li: 캐시 유지")

    # SMM Battery Index
    smm = await fetch_smm_battery_index()
    if smm:
        CACHE["smm"]["system"].update({**smm["system"], "unit": "USD/kWh", "updated": now})
        CACHE["smm"]["cell"].update({**smm["cell"], "unit": "USD/kWh", "updated": now})
        log.info(f"  ✅ SMM System: ${CACHE['smm']['system']['price']}/kWh")
    else:
        CACHE["smm"]["updated"] = now
        log.warning("  ⚠️  SMM Index: SMM API 키 필요 (캐시 유지)")

    CACHE["last_full_update"] = now
    CACHE["status"] = "ok"
    log.info("✅ 데이터 갱신 완료")

# ═══════════════════════════════════════════════
# 5. API 엔드포인트
# ═══════════════════════════════════════════════
@app.get("/")
async def root():
    return {"service": "GESS Raw Material API", "version": "1.0.0", "docs": "/docs"}

@app.get("/api/prices")
async def get_all_prices():
    """모든 원자재 가격 한 번에 반환"""
    return JSONResponse({
        "status": CACHE["status"],
        "last_update": CACHE["last_full_update"],
        "data": {
            "lithium_carbonate": {**CACHE["li"]},
            "aluminum":          {**CACHE["al"]},
            "copper":            {**CACHE["cu"]},
            "smm_index":         {
                "system": {**CACHE["smm"]["system"]},
                "cell":   {**CACHE["smm"]["cell"]},
                "updated": CACHE["smm"]["updated"]
            }
        }
    })

@app.get("/api/prices/{commodity}")
async def get_price(commodity: str):
    """단일 원자재 가격 조회 (li / al / cu / smm)"""
    key_map = {"li": "li", "al": "al", "cu": "cu"}
    if commodity == "smm":
        return CACHE["smm"]
    if commodity not in key_map:
        raise HTTPException(status_code=404, detail=f"Unknown commodity: {commodity}. Use: li, al, cu, smm")
    return CACHE[key_map[commodity]]

@app.get("/api/refresh")
async def manual_refresh():
    """수동 즉시 갱신 (테스트용)"""
    await refresh_all()
    return {"status": "refreshed", "timestamp": CACHE["last_full_update"]}

@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "smm_api_connected": bool(SMM_API_KEY),
        "last_update": CACHE["last_full_update"],
        "cache_status": CACHE["status"]
    }

# ═══════════════════════════════════════════════
# 6. 스케줄러 (1시간마다 자동 갱신)
# ═══════════════════════════════════════════════
scheduler = AsyncIOScheduler(timezone="Asia/Seoul")

@app.on_event("startup")
async def startup():
    log.info("🚀 GESS Server 시작")
    await refresh_all()           # 서버 시작 즉시 1회 갱신
    scheduler.add_job(refresh_all, "interval", hours=1, id="refresh_job")
    scheduler.start()
    log.info("⏰ 스케줄러 시작 (1시간 간격)")

@app.on_event("shutdown")
async def shutdown():
    scheduler.shutdown()

# ═══════════════════════════════════════════════
if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("server:app", host="0.0.0.0", port=port, reload=False)
