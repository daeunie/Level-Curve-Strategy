"""최초 1회: 노트북이 쓰던 Bloomberg 파일 → 대시보드 입력 파일로 변환.

만드는 파일
- inputs/bloomberg_monthly.csv : 월말 OAD 5개 + LUATTRUU 지수 값 (이후 팀이 매월 한 줄씩 추가)
- inputs/history/etf_tr_monthly.csv : SHY~TLT Bloomberg 총수익 지수 월말 값 (백테스트 구간 수익률용, 이후 고정)

HISTORY_END 이후 달은 넣지 않는다. 9월처럼 달이 끝나기 전에 받은 값이 "월말"로 들어가는 것을 막기 위해서다.
이미 파일이 있으면 덮어쓰지 않는다 (--force로 강제).
"""
import sys
from pathlib import Path

import pandas as pd

from config import BBG_FILE, ETF_TR_HISTORY, ETFS, TRADES_FILE

SRC = Path(__file__).resolve().parent.parent          # style investing code 폴더
D_BBG = SRC / "drive-download-20260927T124721Z-1-001"
HISTORY_END = pd.Period("2026-08", "M")
OAD_COL = {"LUATTRUU_OAD": "luattruu_oad", "SHY_OAD": "i28478 index_oad", "IEI_OAD": "lt13stat index_oad",
           "IEF_OAD": "lt09stat index_oad", "TLT_OAD": "lt11stat index_oad"}


def _pair(df, dcol, vcol):
    s = pd.Series(pd.to_numeric(df.iloc[:, vcol], errors="coerce").values,
                  index=pd.to_datetime(df.iloc[:, dcol], errors="coerce"))
    s = s[s.index.notna()].dropna()
    return s[~s.index.duplicated()].sort_index()


def month_last(s):
    """그 달의 마지막 관측값"""
    return s.resample("ME").last().dropna().to_period("M")


def main(force=False):
    for p in [BBG_FILE, ETF_TR_HISTORY]:
        if p.exists() and not force:
            sys.exit(f"{p.name}이(가) 이미 있습니다. 덮어쓰려면 --force")

    # OAD: [날짜, 값, 빈칸] 3열 블록
    raw = pd.read_csv(SRC / "bloomberg oad data monthly.csv", encoding="utf-8-sig")
    oad = {}
    for i in range(0, raw.shape[1], 3):
        s = pd.Series(raw.iloc[:, i + 1].to_numpy(float),
                      index=pd.to_datetime(raw.iloc[:, i], format="%m/%d/%Y")).dropna()
        oad[raw.columns[i + 1]] = s
    oad_df = pd.DataFrame({k: oad[v] for k, v in OAD_COL.items()})

    # LUATTRUU 지수 (일간) → 월말
    raw_bbg = pd.read_excel(D_BBG / "bbg_index_and_oad.xlsx", sheet_name="value", header=None).iloc[2:]
    px = month_last(_pair(raw_bbg, 1, 2))

    out = oad_df.copy()
    out.index = out.index.to_period("M")
    out["LUATTRUU_PX"] = px.reindex(out.index)
    out["date"] = oad_df.index
    out = out.loc[:HISTORY_END]
    BBG_FILE.parent.mkdir(parents=True, exist_ok=True)
    out[["date"] + list(OAD_COL) + ["LUATTRUU_PX"]].assign(date=lambda d: d["date"].dt.strftime("%Y-%m-%d")) \
        .to_csv(BBG_FILE, index=False, encoding="utf-8-sig")

    # ETF 총수익 지수: ETF마다 [날짜, TR, PX_LAST, 빈칸] 4열 블록 → 월말
    raw_tr = pd.read_excel(D_BBG / "shy부터 tlt 까지 tot_ret_ind_grs_div 과 px_last.xlsx",
                           sheet_name="value only", header=None)
    tr = pd.DataFrame({e: month_last(_pair(raw_tr, 4 * i, 4 * i + 1)) for i, e in enumerate(ETFS)})
    tr = tr.loc[:HISTORY_END]
    ETF_TR_HISTORY.parent.mkdir(parents=True, exist_ok=True)
    tr.assign(date=tr.index.to_timestamp(how="end").strftime("%Y-%m-%d"))[["date"] + ETFS] \
        .to_csv(ETF_TR_HISTORY, index=False, encoding="utf-8-sig")

    if not TRADES_FILE.exists():
        pd.DataFrame(columns=["date", "type", "ticker", "shares", "price", "fee", "amount", "memo"]) \
            .to_csv(TRADES_FILE, index=False, encoding="utf-8-sig")

    print(f"bloomberg_monthly.csv: {out.index.min()} ~ {out.index.max()} ({len(out)}개월)")
    print(f"etf_tr_monthly.csv: {tr.index.min()} ~ {tr.index.max()} ({len(tr)}개월)")


if __name__ == "__main__":
    main(force="--force" in sys.argv)
