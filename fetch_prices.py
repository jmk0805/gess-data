"""
GESS Price Crawler
GitHub Actions에서 1시간마다 실행
"""
import json, httpx, os
from datetime import datetime, timezone

HEADERS = {"User-Agent": "Mozilla/5.0"}

def fetch_yahoo(ticker):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
    try:
        r = httpx.get(url, params={"interval":"1d","range":"5d"},
                      headers=HEADERS, timeout=15)
        meta = r.json()["chart"]["result"][0]["meta"]
        price = meta.get("regularMarketPrice") or meta.get("previousClose")
        prev  = meta.get("chartPreviousClose") or price
        chg   = round((price - prev) / prev * 100, 2) if prev else 0.0
        return {"price": price, "chg_pct": chg}
    except Exception as e:
        print(f"  ⚠ Yahoo {ticker} 실패: {e}")
        return None

def main():
    now = datetime.now(timezone.utc).isoformat()
    print(f"🔄 크롤링 시작: {now}")

    # 기존 데이터 로드 (실패시 fallback 유지용)
    try:
        with open("data/prices.json") as f:
            existing = json.load(f)
    except:
        existing = {}

    def prev(key, subkey, default):
        try: return existing["data"][key][subkey]
        except: return default

    # ── 구리 HG=F (USD/lb → USD/mt)
    cu = fetch_yahoo("HG=F")
    if cu:
        cu["price"] = round(cu["price"] * 2204.62, 0)
        cu["unit"]  = "USD/mt"
        cu["source"] = "Yahoo Finance (COMEX HG=F)"
        print(f"  ✅ Cu: ${cu['price']:,.0f}/mt ({cu['chg_pct']:+.2f}%)")
    else:
        cu = {"price": prev("copper","price",12930),
              "chg_pct": 0, "unit":"USD/mt", "source":"캐시(fallback)"}

    # ── 알루미늄 ALI=F (USD/mt)
    al = fetch_yahoo("ALI=F")
    if al:
        al["unit"]   = "USD/mt"
        al["source"] = "Yahoo Finance (LME ALI=F)"
        print(f"  ✅ Al: ${al['price']:,.0f}/mt ({al['chg_pct']:+.2f}%)")
    else:
        al = {"price": prev("aluminum","price",3538),
              "chg_pct": 0, "unit":"USD/mt", "source":"캐시(fallback)"}

    # ── 탄산리튬 (SMM API 키 있으면 실시간, 없으면 캐시 유지)
    smm_key = os.getenv("SMM_API_KEY", "")
    if smm_key:
        # TODO: SMM 계약 후 실제 API 호출로 교체
        li = {"price": prev("lithium_carbonate","price",19.46),
              "chg_pct": 0, "unit":"USD/kg", "source":"SMM API (연동 예정)"}
    else:
        li = {"price": prev("lithium_carbonate","price",19.46),
              "chg_pct": prev("lithium_carbonate","chg_pct",0),
              "unit":"USD/kg", "source":"캐시(SMM 계약 후 실시간)"}
        print(f"  ⚠ Li: SMM API 키 없음 → 캐시 유지 ({li['price']})")

    # ── SMM Battery Index (계약 전 수동값)
    smm = {
        "system": {"price": 82.6, "unit":"USD/kWh",
                   "chg_pct": -3.1, "source":"SMM(수동갱신)"},
        "cell":   {"price": 45.1, "unit":"USD/kWh",
                   "chg_pct": -3.6, "source":"SMM(수동갱신)"},
        "updated": now
    }

    # ── 히스토리 누적 (최근 168개 = 1주일치 1시간 간격)
    history = existing.get("history", [])
    history.append({
        "timestamp": now,
        "li":  li["price"],
        "al":  al["price"],
        "cu":  cu["price"],
        "smm_system": smm["system"]["price"],
        "smm_cell":   smm["cell"]["price"]
    })
    history = history[-168:]  # 최근 168개만 유지

    # ── 저장
    output = {
        "status":  "ok",
        "updated": now,
        "data": {
            "lithium_carbonate": li,
            "aluminum":          al,
            "copper":            cu,
            "smm_index":         smm
        },
        "history": history
    }

    with open("data/prices.json", "w") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"✅ data/prices.json 저장 완료")

if __name__ == "__main__":
    main()
