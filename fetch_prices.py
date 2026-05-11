"""
GESS Price Crawler
GitHub Actions에서 1시간마다 실행 → prices.json 누적 저장
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

    # 기존 데이터 로드 (히스토리 누적용)
    try:
        with open("data/prices.json") as f:
            existing = json.load(f)
        print(f"  기존 히스토리: {len(existing.get('history', []))}개")
    except:
        existing = {}
        print("  기존 데이터 없음 — 새로 시작")

    def prev_val(key, subkey, default):
        try: return existing["data"][key][subkey]
        except: return default

    # ── 구리 HG=F (USD/lb → USD/mt 변환)
    cu = fetch_yahoo("HG=F")
    if cu:
        cu["price"] = round(cu["price"] * 2204.62, 0)
        cu["unit"]  = "USD/mt"
        cu["source"] = "Yahoo Finance (COMEX HG=F)"
        print(f"  ✅ Cu: ${cu['price']:,.0f}/mt ({cu['chg_pct']:+.2f}%)")
    else:
        cu = {
            "price":   prev_val("copper", "price", 13845),
            "chg_pct": 0,
            "unit":    "USD/mt",
            "source":  "캐시(fallback)"
        }

    # ── 알루미늄 ALI=F (USD/mt)
    al = fetch_yahoo("ALI=F")
    if al:
        al["unit"]   = "USD/mt"
        al["source"] = "Yahoo Finance (LME ALI=F)"
        print(f"  ✅ Al: ${al['price']:,.0f}/mt ({al['chg_pct']:+.2f}%)")
    else:
        al = {
            "price":   prev_val("aluminum", "price", 3461),
            "chg_pct": 0,
            "unit":    "USD/mt",
            "source":  "캐시(fallback)"
        }

    # ── 탄산리튬 (SMM API 키 있으면 실시간, 없으면 직전값 유지)
    smm_key = os.getenv("SMM_API_KEY", "")
    li_price = prev_val("lithium_carbonate", "price", 19.46)
    li_chg   = prev_val("lithium_carbonate", "chg_pct", 0)
    if smm_key:
        # SMM 계약 후 실제 API 호출로 교체
        li = {"price": li_price, "chg_pct": li_chg,
              "unit": "USD/kg", "source": "SMM API"}
    else:
        li = {"price": li_price, "chg_pct": li_chg,
              "unit": "USD/kg", "source": "캐시(SMM 계약 후 실시간)"}
        print(f"  ⚠ Li: SMM 키 없음 → 직전값 유지 (${li_price}/kg)")

    # ── SMM Battery Index (SMM 계약 전 수동값 유지)
    smm = {
        "system": {
            "price":   prev_val("smm_index", "system", {}).get("price", 82.6),
            "unit":    "USD/kWh",
            "chg_pct": prev_val("smm_index", "system", {}).get("chg_pct", -3.1),
            "source":  "SMM(수동갱신)"
        },
        "cell": {
            "price":   prev_val("smm_index", "cell", {}).get("price", 45.1),
            "unit":    "USD/kWh",
            "chg_pct": prev_val("smm_index", "cell", {}).get("chg_pct", -3.6),
            "source":  "SMM(수동갱신)"
        },
        "updated": now
    }

    # ── 히스토리 누적 (개수 제한 없음 — 전체 보존)
    history = existing.get("history", [])
    history.append({
        "timestamp":  now,
        "li":         li["price"],
        "al":         al["price"],
        "cu":         cu["price"],
        "smm_system": smm["system"]["price"],
        "smm_cell":   smm["cell"]["price"]
    })
    # 제한 없이 전체 보존 (디스크 용량 걱정 없음 — 1시간마다 한 줄 = 연 8,760줄)

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

    os.makedirs("data", exist_ok=True)
    with open("data/prices.json", "w") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"✅ 저장 완료 — 누적 히스토리: {len(history)}개")

if __name__ == "__main__":
    main()
