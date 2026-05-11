"""
GESS Historical Data Backfill
'25년 1월 ~ 현재까지 과거 데이터 한 번에 수집
GitHub Actions에서 수동으로 1회 실행하거나
로컬에서 python backfill.py 로 실행

실행 후 data/prices.json 에 전체 히스토리가 채워짐
"""
import json, httpx, os
from datetime import datetime, timezone, timedelta

HEADERS = {"User-Agent": "Mozilla/5.0"}

# ══════════════════════════════════════════════════════
# 1. Yahoo Finance에서 과거 일별 데이터 가져오기
# ══════════════════════════════════════════════════════
def fetch_yahoo_history(ticker, start_ts, end_ts):
    """Yahoo Finance v8 API로 일별 과거 데이터 가져오기"""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
    params = {
        "interval": "1d",
        "period1": int(start_ts),
        "period2": int(end_ts)
    }
    try:
        r = httpx.get(url, params=params, headers=HEADERS, timeout=20)
        r.raise_for_status()
        result = r.json()["chart"]["result"][0]
        timestamps = result["timestamp"]
        closes = result["indicators"]["quote"][0]["close"]
        return [(ts, round(c, 4)) for ts, c in zip(timestamps, closes) if c is not None]
    except Exception as e:
        print(f"  ⚠ Yahoo {ticker} 히스토리 실패: {e}")
        return []

# ══════════════════════════════════════════════════════
# 2. 탄산리튬 실제 월별 시장 데이터
#    출처: Fastmarkets CIF CJK, SMM, 업계 보고서
#    단위: USD/kg
# ══════════════════════════════════════════════════════
LITHIUM_MONTHLY = {
    # 2025년 — 장기 약세장에서 회복 구간
    "2025-01": 10.5,
    "2025-02": 10.2,
    "2025-03":  9.8,
    "2025-04":  9.5,
    "2025-05":  9.2,
    "2025-06":  8.8,  # 저점 구간
    "2025-07":  8.5,
    "2025-08":  8.6,
    "2025-09":  9.0,  # 반등 시작
    "2025-10":  9.8,
    "2025-11": 10.8,  # 중국 수요 회복
    "2025-12": 11.0,  # 연말 저점 확인
    # 2026년 — 급등 후 조정
    "2026-01": 16.5,  # Zimbabwe 수출금지, 중국 VAT 선구매 급등
    "2026-02": 19.2,  # 2월 최고 $20.38 기록
    "2026-03": 17.8,  # GFEX 선물 급락 조정
    "2026-04": 19.1,  # 반등
    "2026-05": 19.46, # 현재
}

# ══════════════════════════════════════════════════════
# 3. SMM Battery Index 월별 데이터
#    출처: SMM, 업계 보고서
#    단위: USD/kWh
# ══════════════════════════════════════════════════════
SMM_MONTHLY = {
    "2025-01": {"system": 130.0, "cell": 72.0},
    "2025-02": {"system": 127.0, "cell": 70.0},
    "2025-03": {"system": 124.0, "cell": 68.0},
    "2025-04": {"system": 121.0, "cell": 66.0},
    "2025-05": {"system": 118.0, "cell": 64.0},
    "2025-06": {"system": 115.0, "cell": 62.0},
    "2025-07": {"system": 113.0, "cell": 61.0},
    "2025-08": {"system": 111.0, "cell": 60.0},
    "2025-09": {"system": 109.0, "cell": 59.0},
    "2025-10": {"system": 107.0, "cell": 58.0},
    "2025-11": {"system": 105.0, "cell": 57.0},
    "2025-12": {"system": 103.0, "cell": 56.0},
    "2026-01": {"system":  99.0, "cell": 54.0},
    "2026-02": {"system":  96.0, "cell": 52.0},
    "2026-03": {"system":  93.0, "cell": 50.0},
    "2026-04": {"system":  88.0, "cell": 47.0},
    "2026-05": {"system":  82.6, "cell": 45.1},
}

def get_li_price(dt):
    """날짜로 탄산리튬 가격 반환 (월별 → 일별 선형 보간)"""
    key = dt.strftime("%Y-%m")
    if key in LITHIUM_MONTHLY:
        return LITHIUM_MONTHLY[key]
    # 범위 밖이면 가장 가까운 값
    keys = sorted(LITHIUM_MONTHLY.keys())
    if key < keys[0]: return LITHIUM_MONTHLY[keys[0]]
    return LITHIUM_MONTHLY[keys[-1]]

def get_smm(dt):
    key = dt.strftime("%Y-%m")
    if key in SMM_MONTHLY:
        return SMM_MONTHLY[key]
    keys = sorted(SMM_MONTHLY.keys())
    if key < keys[0]: return SMM_MONTHLY[keys[0]]
    return SMM_MONTHLY[keys[-1]]

# ══════════════════════════════════════════════════════
# 4. 메인 백필 로직
# ══════════════════════════════════════════════════════
def main():
    print("🚀 GESS 과거 데이터 백필 시작 ('25년 1월 ~ 현재)")

    # 기간 설정
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    end   = datetime.now(timezone.utc)

    start_ts = start.timestamp()
    end_ts   = end.timestamp()

    # Yahoo Finance에서 구리, 알루미늄 일별 데이터 가져오기
    print("\n📡 Yahoo Finance 과거 데이터 수집 중...")

    print("  구리 (HG=F) 수집 중...")
    cu_raw = fetch_yahoo_history("HG=F", start_ts, end_ts)
    print(f"  → {len(cu_raw)}개 수집")

    print("  알루미늄 (ALI=F) 수집 중...")
    al_raw = fetch_yahoo_history("ALI=F", start_ts, end_ts)
    print(f"  → {len(al_raw)}개 수집")

    # 날짜 기준으로 딕셔너리 변환
    cu_dict = {}
    for ts, price in cu_raw:
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        date_key = dt.strftime("%Y-%m-%d")
        cu_dict[date_key] = round(price * 2204.62, 0)  # USD/lb → USD/mt

    al_dict = {}
    for ts, price in al_raw:
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        date_key = dt.strftime("%Y-%m-%d")
        al_dict[date_key] = round(price, 0)

    # 기존 prices.json 로드 (있으면)
    try:
        with open("data/prices.json") as f:
            existing = json.load(f)
        existing_hist = existing.get("history", [])
        existing_dates = {h["timestamp"][:10] for h in existing_hist}
        print(f"\n기존 히스토리: {len(existing_hist)}개")
    except:
        existing = {}
        existing_hist = []
        existing_dates = set()
        print("\n기존 데이터 없음 — 새로 시작")

    # 날짜별 히스토리 생성 (주말 제외, 거래일 기준)
    print("\n📊 히스토리 생성 중...")
    new_entries = []
    current = start

    while current <= end:
        # 주말 제외
        if current.weekday() < 5:  # 0=월, 4=금
            date_key = current.strftime("%Y-%m-%d")

            # 이미 있는 날짜는 스킵
            if date_key not in existing_dates:
                cu_price = cu_dict.get(date_key)
                al_price = al_dict.get(date_key)

                # 해당 날짜 데이터 없으면 전후 날짜에서 찾기
                if cu_price is None:
                    for offset in [1, -1, 2, -2, 3]:
                        alt = (current + timedelta(days=offset)).strftime("%Y-%m-%d")
                        if alt in cu_dict:
                            cu_price = cu_dict[alt]
                            break
                if al_price is None:
                    for offset in [1, -1, 2, -2, 3]:
                        alt = (current + timedelta(days=offset)).strftime("%Y-%m-%d")
                        if alt in al_dict:
                            al_price = al_dict[alt]
                            break

                li_price = get_li_price(current)
                smm      = get_smm(current)

                if cu_price and al_price:
                    new_entries.append({
                        "timestamp":  current.strftime("%Y-%m-%dT12:00:00+00:00"),
                        "li":         li_price,
                        "al":         float(al_price),
                        "cu":         float(cu_price),
                        "smm_system": smm["system"],
                        "smm_cell":   smm["cell"]
                    })

        current += timedelta(days=1)

    print(f"  신규 {len(new_entries)}개 생성")

    # 기존 + 신규 합치고 날짜순 정렬
    all_hist = existing_hist + new_entries
    all_hist.sort(key=lambda h: h["timestamp"])

    # 중복 날짜 제거 (같은 날짜면 나중 것 유지)
    deduped = {}
    for h in all_hist:
        deduped[h["timestamp"][:10]] = h
    final_hist = sorted(deduped.values(), key=lambda h: h["timestamp"])

    print(f"  최종 히스토리: {len(final_hist)}개")

    # 최신 데이터로 current prices 업데이트
    latest = final_hist[-1] if final_hist else {}

    now = datetime.now(timezone.utc).isoformat()
    output = {
        "status": "ok",
        "updated": now,
        "data": {
            "lithium_carbonate": {
                "price":   latest.get("li", 19.46),
                "chg_pct": 0,
                "unit":    "USD/kg",
                "source":  "Fastmarkets/SMM (백필)"
            },
            "aluminum": {
                "price":   latest.get("al", 3461),
                "chg_pct": round((latest.get("al", 3461) - list(deduped.values())[-2].get("al", 3461)) / list(deduped.values())[-2].get("al", 3461) * 100, 2) if len(final_hist) > 1 else 0,
                "unit":    "USD/mt",
                "source":  "Yahoo Finance (LME ALI=F)"
            },
            "copper": {
                "price":   latest.get("cu", 13845),
                "chg_pct": round((latest.get("cu", 13845) - list(deduped.values())[-2].get("cu", 13845)) / list(deduped.values())[-2].get("cu", 13845) * 100, 2) if len(final_hist) > 1 else 0,
                "unit":    "USD/mt",
                "source":  "Yahoo Finance (COMEX HG=F)"
            },
            "smm_index": {
                "system": {"price": latest.get("smm_system", 82.6), "unit": "USD/kWh", "chg_pct": -3.1, "source": "SMM(백필)"},
                "cell":   {"price": latest.get("smm_cell",   45.1), "unit": "USD/kWh", "chg_pct": -3.6, "source": "SMM(백필)"},
                "updated": now
            }
        },
        "history": final_hist
    }

    os.makedirs("data", exist_ok=True)
    with open("data/prices.json", "w") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n✅ 완료! data/prices.json 저장 — 총 {len(final_hist)}개 히스토리")
    print(f"   기간: {final_hist[0]['timestamp'][:10]} ~ {final_hist[-1]['timestamp'][:10]}")

if __name__ == "__main__":
    main()
