"""데이터 읽기·자동 수신·검증.

- FRED 금리: API 키 없이 fredgraph CSV로 자동 수신 → cache/fred_daily.csv
- ETF 가격: yfinance 자동 수신 → cache/prices_adj.csv (수정주가), cache/prices_close.csv (종가, 계좌 평가용)
- Bloomberg OAD 5개 + LUATTRUU 지수 값: 팀이 inputs/bloomberg_monthly.csv에 매월 말 입력
- ETF 월 수익률: 2026-08까지는 백테스트와 같은 Bloomberg 총수익 지수, 그 뒤는 yfinance 수정주가
"""
import io
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests
from pandas.tseries.holiday import USFederalHolidayCalendar
from pandas.tseries.offsets import CustomBusinessMonthEnd

from config import (BBG_FILE, BBG_VS_SPTB_WARN, BENCH_ETF, CACHE, CACHE_HOURS, ETF_TR_HISTORY, ETFS,
                    FRED_SERIES, OAD_JUMP_WARN, PRICE_START)

BBG_COLS = ["LUATTRUU_OAD", "SHY_OAD", "IEI_OAD", "IEF_OAD", "TLT_OAD", "LUATTRUU_PX"]
BBG_LABELS = {"LUATTRUU_OAD": "LUATTRUU Index OAD (지수)", "SHY_OAD": "I28478 Index OAD (SHY)",
              "IEI_OAD": "LT13STAT Index OAD (IEI)", "IEF_OAD": "LT09STAT Index OAD (IEF)",
              "TLT_OAD": "LT11STAT Index OAD (TLT)", "LUATTRUU_PX": "LUATTRUU Index PX_LAST"}
_BME = CustomBusinessMonthEnd(calendar=USFederalHolidayCalendar())
_ET = ZoneInfo("America/New_York")


# ── 달이 끝났는지 ──
def last_bday(m):
    """그 달의 마지막 미국 영업일"""
    return (m.to_timestamp() + _BME).normalize()


def complete_through(index):
    """관측일 목록으로 판단한, 데이터가 끝까지 들어온 마지막 달"""
    last = pd.Timestamp(index.max()).normalize()
    m = last.to_period("M")
    return m if last >= last_bday(m) else m - 1


# ── 자동 수신 ──
def _fresh(path):
    return path.exists() and time.time() - path.stat().st_mtime < CACHE_HOURS * 3600


def fetch_fred(force=False):
    """FRED 일간 금리 (소수). 열 = 2, 5, 10, 20, "3M". 실패하면 마지막 캐시를 쓴다."""
    path = CACHE / "fred_daily.csv"
    if force or not _fresh(path):
        try:
            cols = {}
            for key, sid in FRED_SERIES.items():
                r = requests.get("https://fred.stlouisfed.org/graph/fredgraph.csv", params={"id": sid}, timeout=30)
                r.raise_for_status()
                df = pd.read_csv(io.StringIO(r.text), na_values=["."])
                cols[sid] = pd.Series(pd.to_numeric(df.iloc[:, 1], errors="coerce").values,
                                      index=pd.to_datetime(df.iloc[:, 0]))
            CACHE.mkdir(exist_ok=True)
            pd.DataFrame(cols).rename_axis("date").to_csv(path)
        except Exception as e:
            if not path.exists():
                raise RuntimeError(f"FRED 수신 실패, 캐시도 없음: {e}") from e
    raw = pd.read_csv(path, index_col=0, parse_dates=True)
    out = pd.DataFrame({k: raw[sid] / 100 for k, sid in FRED_SERIES.items()})
    return out.dropna(how="all")


def fetch_prices(force=False):
    """yfinance 일간 가격 → (수정주가, 종가). 미국 장중이면 오늘 행은 뺀다 (장 마감 전 가격)."""
    p_adj, p_close = CACHE / "prices_adj.csv", CACHE / "prices_close.csv"
    if force or not (_fresh(p_adj) and _fresh(p_close)):
        try:
            import yfinance as yf
            raw = yf.download(ETFS + [BENCH_ETF], start=PRICE_START, auto_adjust=False,
                              progress=False, threads=False)
            if raw.empty:
                raise RuntimeError("빈 데이터")
            CACHE.mkdir(exist_ok=True)
            raw["Adj Close"].rename_axis("date").to_csv(p_adj)
            raw["Close"].rename_axis("date").to_csv(p_close)
        except Exception as e:
            if not p_adj.exists():
                raise RuntimeError(f"yfinance 수신 실패, 캐시도 없음: {e}") from e
    adj = pd.read_csv(p_adj, index_col=0, parse_dates=True)
    close = pd.read_csv(p_close, index_col=0, parse_dates=True)
    now = datetime.now(_ET)
    if now.hour < 17:                                  # 미국 동부 17시 전이면 오늘 가격은 미확정
        today = pd.Timestamp(now.date())
        adj, close = adj[adj.index < today], close[close.index < today]
    return adj, close


# ── 팀 입력: Bloomberg 월말 값 ──
def load_bbg():
    """inputs/bloomberg_monthly.csv → 월(Period) 인덱스 DataFrame"""
    df = pd.read_csv(BBG_FILE, encoding="utf-8-sig")
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date")
    df.index = pd.PeriodIndex(df["date"], freq="M")
    df = df[~df.index.duplicated(keep="last")]
    full = pd.period_range(df.index.min(), df.index.max(), freq="M")
    return df.reindex(full)


def check_bbg_row(row, bbg, sptb_ret):
    """새로 넣을 한 달 값 검사 → (오류 목록, 경고 목록). 오류가 있으면 저장하지 않는다."""
    errors, warns = [], []
    date = pd.Timestamp(row["date"])
    m = date.to_period("M")
    last_m = bbg.index.max()
    if m <= last_m and bbg.loc[m, BBG_COLS[:5]].notna().all():
        errors.append(f"{m} 값이 이미 있습니다. 고치려면 inputs/bloomberg_monthly.csv를 직접 수정하세요.")
    if m > last_m + 1:
        warns.append(f"{last_m + 1} ~ {m - 1} 값이 비어 있습니다. 순서대로 넣는 것이 좋습니다.")
    if date.normalize() != last_bday(m):
        warns.append(f"날짜가 {m}의 마지막 영업일({last_bday(m):%Y-%m-%d})이 아닙니다.")
    for c in BBG_COLS[:5]:
        v = row.get(c)
        if v is None or not np.isfinite(v) or v <= 0:
            errors.append(f"{BBG_LABELS[c]}: 값이 비었거나 0 이하입니다.")
    if errors:
        return errors, warns
    prev = bbg[BBG_COLS].dropna(subset=BBG_COLS[:5])
    prev = prev[prev.index < m]
    if len(prev):
        p = prev.iloc[-1]
        for c in BBG_COLS[:5]:
            if abs(row[c] - p[c]) > OAD_JUMP_WARN:
                warns.append(f"{BBG_LABELS[c]}: 전월 {p[c]:.3f} → {row[c]:.3f} (변화 {row[c] - p[c]:+.2f}년)")
        if pd.notna(row.get("LUATTRUU_PX")) and pd.notna(p["LUATTRUU_PX"]) and prev.index[-1] == m - 1:
            r_bbg = row["LUATTRUU_PX"] / p["LUATTRUU_PX"] - 1
            r_sptb = sptb_ret.get(m, np.nan)
            if np.isfinite(r_sptb) and abs(r_bbg - r_sptb) > BBG_VS_SPTB_WARN:
                warns.append(f"LUATTRUU 월 수익률 {r_bbg:+.2%} vs SPTB {r_sptb:+.2%} (차이가 큽니다. 지수 값을 확인하세요)")
    if pd.isna(row.get("LUATTRUU_PX")):
        warns.append("LUATTRUU 지수 값이 비었습니다. 이 달 Bloomberg 벤치마크 수익률이 빠집니다.")
    return errors, warns


def append_bbg(row):
    df = pd.read_csv(BBG_FILE, encoding="utf-8-sig")
    new = {"date": pd.Timestamp(row["date"]).strftime("%Y-%m-%d")} | {c: row.get(c) for c in BBG_COLS}
    pd.concat([df, pd.DataFrame([new])], ignore_index=True).to_csv(BBG_FILE, index=False, encoding="utf-8-sig")


# ── 조립 ──
def monthly_returns(prices, through):
    """일간 가격 → 월 수익률 (through 달까지)"""
    m = prices.resample("ME").last().to_period("M")
    return m.pct_change(fill_method=None).loc[:through]


def assemble(force=False):
    """대시보드가 쓰는 모든 데이터를 한 번에 준비한다."""
    fred = fetch_fred(force)
    adj, close = fetch_prices(force)
    bbg = load_bbg()

    fred_done = complete_through(fred.dropna().index)
    price_done = complete_through(adj[ETFS].dropna().index)
    oad_ok = bbg.dropna(subset=BBG_COLS[:5])
    oad_done = oad_ok.index.max()

    # 스타일 점수는 끝난 달까지의 금리로만 계산 (이번 달 일부 데이터가 "월말"로 쓰이지 않게)
    fred_cut = fred.loc[:last_bday(fred_done) + pd.Timedelta(days=1)]

    # ETF 월 수익률: Bloomberg 총수익 지수(백테스트와 동일) + 그 뒤 yfinance 수정주가
    hist = pd.read_csv(ETF_TR_HISTORY, encoding="utf-8-sig")
    hist.index = pd.PeriodIndex(pd.to_datetime(hist["date"]), freq="M")
    hist_ret = hist[ETFS].pct_change(fill_method=None)
    yf_ret = monthly_returns(adj[ETFS], price_done)
    tail = yf_ret[yf_ret.index > hist.index.max()]
    etf_ret = pd.concat([hist_ret, tail])
    etf_src = pd.Series(["Bloomberg TR"] * len(hist_ret) + ["yfinance"] * len(tail), index=etf_ret.index)

    sptb_ret = monthly_returns(adj[[BENCH_ETF]].dropna(), price_done)[BENCH_ETF].dropna()
    bbg_ret = (bbg["LUATTRUU_PX"] / bbg["LUATTRUU_PX"].shift(1) - 1).dropna()

    duration = oad_ok[[f"{e}_OAD" for e in ETFS]].set_axis(ETFS, axis=1)
    status = pd.DataFrame([
        {"데이터": "FRED 금리 (자동)", "마지막 관측일": fred.dropna().index.max().date(), "끝난 마지막 달": fred_done},
        {"데이터": "ETF 가격 yfinance (자동)", "마지막 관측일": adj[ETFS].dropna().index.max().date(),
         "끝난 마지막 달": price_done},
        {"데이터": "Bloomberg OAD (팀 입력)", "마지막 관측일": oad_ok["date"].max().date(), "끝난 마지막 달": oad_done},
        {"데이터": "LUATTRUU 지수 (팀 입력)", "마지막 관측일": bbg["date"][bbg["LUATTRUU_PX"].notna()].max().date(),
         "끝난 마지막 달": bbg["LUATTRUU_PX"].dropna().index.max()},
    ])
    return {"fred": fred_cut, "close": close, "bbg": bbg, "duration": duration,
            "bbg_duration": oad_ok["LUATTRUU_OAD"], "etf_ret": etf_ret, "etf_src": etf_src,
            "bbg_ret": bbg_ret, "sptb_ret": sptb_ret, "yf_ret": yf_ret, "fred_done": fred_done, "price_done": price_done,
            "oad_done": oad_done, "status": status, "fred_last": fred.dropna().index.max()}
