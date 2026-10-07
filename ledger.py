"""결정 기록과 실제 계좌.

- records/decision_log.csv: 매달 확정한 결정(점수·λ·비중)을 한 줄씩 추가만 한다.
  나중에 데이터가 바뀌어 다시 계산해도, 그때 실제로 정한 비중은 이 기록이 기준이다.
- inputs/trades.csv: 실제 계좌의 입출금·매매·배당. 계좌 가치는 종가(수정 전)로 평가한다.
"""
from datetime import datetime

import numpy as np
import pandas as pd

from config import DECISION_LOG, ETFS, TRADES_FILE

TRADE_TYPES = {"DEPOSIT": "입금", "WITHDRAW": "출금", "BUY": "매수", "SELL": "매도", "DIVIDEND": "배당(세후)"}
TRADE_COLS = ["date", "type", "ticker", "shares", "price", "fee", "amount", "memo"]


# ── 결정 기록 ──
def load_log():
    if not DECISION_LOG.exists():
        return pd.DataFrame()
    df = pd.read_csv(DECISION_LOG, encoding="utf-8-sig")
    df["decision_month"] = pd.PeriodIndex(df["decision_month"], freq="M")
    return df


def log_row(strategy, t, res, score, D, meta):
    """한 전략의 한 달 결정 → 기록 한 줄. D = 결정 월 ETF OAD, meta = 데이터 날짜 등"""
    row = {"decision_month": str(t), "hold_month": str(t + 1), "strategy": strategy,
           "recorded_at": datetime.now().strftime("%Y-%m-%d %H:%M")} | meta
    row |= {"D_target": float(res["w"].loc[t].to_numpy(float) @ D), "λ": res["λ"].loc[t],
            "L": res["L"].loc[t], "ΔD": res["ΔD"].loc[t]}
    for e in ETFS:
        row[f"score_{e}"] = score.loc[t, e] if score is not None else np.nan
        row[f"N_{e}"] = res["N"].loc[t, e]
        row[f"aL_{e}"] = res["a_L"].loc[t, e]
        row[f"aC_{e}"] = res["a_C"].loc[t, e]
        row[f"w_{e}"] = res["w"].loc[t, e]
    return row


def record(rows):
    """이미 기록된 (결정 월, 전략)은 건너뛴다. 새로 추가한 줄 수를 돌려준다."""
    old = load_log()
    done = set() if old.empty else set(zip(old["decision_month"].astype(str), old["strategy"]))
    new = pd.DataFrame([r for r in rows if (r["decision_month"], r["strategy"]) not in done])
    if new.empty:
        return 0
    out = new if old.empty else pd.concat([old.assign(decision_month=old["decision_month"].astype(str)), new],
                                          ignore_index=True)
    DECISION_LOG.parent.mkdir(exist_ok=True)
    out.to_csv(DECISION_LOG, index=False, encoding="utf-8-sig")
    return len(new)


def logged_weights(strategy, log):
    """기록된 결정 월의 비중 (index = 결정 월)"""
    if log.empty:
        return pd.DataFrame(columns=ETFS)
    sub = log[log["strategy"] == strategy].set_index("decision_month")
    return sub[[f"w_{e}" for e in ETFS]].set_axis(ETFS, axis=1)


def with_log(strategy, w, log):
    """다시 계산한 비중에서, 기록이 있는 달은 기록된 비중으로 바꾼다."""
    lw = logged_weights(strategy, log)
    out = w.copy()
    for t in lw.index:
        out.loc[t, ETFS] = lw.loc[t, ETFS].to_numpy(float)
    return out.sort_index()


# ── 계좌 ──
def load_trades():
    if not TRADES_FILE.exists():
        return pd.DataFrame(columns=TRADE_COLS)
    df = pd.read_csv(TRADES_FILE, encoding="utf-8-sig")
    if df.empty:
        return pd.DataFrame(columns=TRADE_COLS)
    df["date"] = pd.to_datetime(df["date"])
    df["type"] = df["type"].str.upper().str.strip()
    for c in ["shares", "price", "fee", "amount"]:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
    return df.sort_values("date", kind="stable")


def append_trade(row):
    df = pd.read_csv(TRADES_FILE, encoding="utf-8-sig") if TRADES_FILE.exists() else pd.DataFrame(columns=TRADE_COLS)
    new = {c: row.get(c, "") for c in TRADE_COLS}
    new["date"] = pd.Timestamp(new["date"]).strftime("%Y-%m-%d")
    pd.concat([df, pd.DataFrame([new])], ignore_index=True).to_csv(TRADES_FILE, index=False, encoding="utf-8-sig")


def cash_effect(t):
    """한 줄이 현금에 주는 영향 (USD)"""
    gross = t["shares"] * t["price"]
    return {"DEPOSIT": t["amount"], "WITHDRAW": -t["amount"], "BUY": -gross - t["fee"],
            "SELL": gross - t["fee"], "DIVIDEND": t["amount"]}.get(t["type"], 0.0)


def positions(trades, asof=None):
    """(보유 수량 Series, 현금)"""
    tr = trades if asof is None else trades[trades["date"] <= asof]
    sign = tr["type"].map({"BUY": 1, "SELL": -1}).fillna(0)
    shares = (tr["shares"] * sign).groupby(tr["ticker"]).sum().reindex(ETFS).fillna(0.0)
    cash = float(tr.apply(cash_effect, axis=1).sum()) if len(tr) else 0.0
    return shares, cash


def account_monthly(trades, close):
    """월말 계좌 가치와 월 수익률 (외부 입출금은 월초에 들어온 것으로 보는 수정 Dietz)"""
    if trades.empty or not trades["type"].isin(["DEPOSIT"]).any():
        return pd.DataFrame(columns=["nav", "flow", "ret"])
    days = close.index[close.index >= trades["date"].min().normalize()]
    sign = trades["type"].map({"BUY": 1, "SELL": -1}).fillna(0)
    sh = (trades.assign(q=trades["shares"] * sign).pivot_table(index="date", columns="ticker", values="q", aggfunc="sum")
          .reindex(columns=ETFS).fillna(0.0))
    idx = days.union(sh.index)
    sh = sh.reindex(idx).fillna(0.0).cumsum()
    cash = trades.assign(c=trades.apply(cash_effect, axis=1)).groupby("date")["c"].sum().reindex(idx).fillna(0.0).cumsum()
    px = close[ETFS].reindex(idx).ffill()
    nav = (sh * px).sum(axis=1) + cash
    flow = trades[trades["type"].isin(["DEPOSIT", "WITHDRAW"])]
    flow = (flow["amount"] * flow["type"].map({"DEPOSIT": 1, "WITHDRAW": -1})).groupby(flow["date"].dt.to_period("M")).sum()
    m = pd.DataFrame({"nav": nav.loc[days].resample("ME").last().to_period("M")})
    m["flow"] = flow.reindex(m.index).fillna(0.0)
    start = m["nav"].shift(1).fillna(0.0)
    m["ret"] = (m["nav"] - start - m["flow"]) / (start + m["flow"])
    return m


def trade_list(w, shares_now, cash, price):
    """목표 비중 → 정수 주 매매 목록 (내림, 남는 돈은 현금)"""
    hold = shares_now.reindex(ETFS).fillna(0.0)
    nav = cash + float((hold * price).sum())
    target = np.floor(w.reindex(ETFS) * nav / price)
    out = pd.DataFrame({"현재 수량": hold, "가격": price, "목표 비중": w.reindex(ETFS),
                        "목표 수량": target, "매매 수량": target - hold})
    out["매매 금액"] = out["매매 수량"] * price
    out["매매 후 비중"] = out["목표 수량"] * price / nav
    left = nav - float((target * price).sum())
    return out, nav, left
