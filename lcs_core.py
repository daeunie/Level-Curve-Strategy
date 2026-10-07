"""LCS 엔진: 스타일 점수 → 수준 + 커브 → 비례 축소 → 백테스트 · 성과 지표.

`LCS strategy.ipynb` 3·4절과 같은 계산이다. 대시보드는 이 파일만 쓰므로,
노트북의 규칙을 바꾸면 이 파일도 같이 바꿔야 실운용 비중이 백테스트와 같아진다.
Value는 기대인플레이션 데이터가 필요해 대시보드에서는 계산하지 않는다.
"""
import numpy as np
import pandas as pd
from scipy.optimize import minimize

from config import (BAND, CURVE_CLIP, CURVE_K, ETFS, LEVEL_FULL, LEVEL_RANGE, MOM_EWM_COM,
                    MOM_HORIZONS, TENOR, Z_WINDOW)


# ── 3절: 스타일 점수 ──
def rolling_z(x, w):
    """이번 달을 포함한 w개월 z-score"""
    mu = x.rolling(w, min_periods=w).mean()
    sd = x.rolling(w, min_periods=w).std(ddof=1)
    return (x - mu) / sd.where(sd > 1e-12)


def weighted_ma(sc):
    """1·3·12 가중 이동평균: (이번 달 + 최근 3개월 평균 + 최근 12개월 평균) / 3
    = 이번 달 47% + 1~2개월 전 각 14% + 3~11개월 전 각 3%"""
    return (sc + sc.rolling(3).mean() + sc.rolling(12).mean()) / 3


def par_price(yp, c, m):
    yp = np.maximum(yp, 1e-7)
    disc = (1 + yp / 2) ** (-2 * m)
    return c / yp * (1 - disc) + disc


def dur_conv(y, m, h=1e-5):
    """쿠폰 = 금리인 par채권의 수정듀레이션·볼록성 (수치 미분)"""
    y = np.asarray(y, dtype=float)
    p0, pu, pd_ = par_price(y, y, m), par_price(y + h, y, m), par_price(y - h, y, m)
    return -(pu - pd_) / (2 * h) / p0, (pu - 2 * p0 + pd_) / h ** 2 / p0


def par_return(y, m, dt):
    """par채권 수익률 근사: 이자 + 듀레이션 효과 + 볼록성 효과"""
    D, C = (pd.Series(v, index=y.index) for v in dur_conv(y.values, m))
    dy = y.diff()
    return y.shift(1) * dt - D.shift(1) * dy + 0.5 * C.shift(1) * dy ** 2


def month_end(s):
    return s.resample("ME").last().dropna().to_period("M")


def style_scores(fred_daily):
    """만기별 Carry · Momentum 점수 (월말). fred_daily 열 = 2, 5, 10, 20, "3M" (소수)"""
    yld = pd.DataFrame({k: month_end(fred_daily[k].dropna()) for k in TENOR.values()})
    y3m = month_end(fred_daily["3M"].dropna())
    cash_ret = y3m.shift(1) / 12
    to_etf = lambda df: df[[TENOR[e] for e in ETFS]].set_axis(ETFS, axis=1)

    # Momentum: 월간 합성 초과수익(분자) / 일간 60일 지수가중 변동성의 월 환산(분모)
    excess = pd.DataFrame({e: par_return(yld[TENOR[e]], TENOR[e], 1 / 12) for e in ETFS}).sub(cash_ret, axis=0)
    yd = fred_daily.dropna()
    dt = yd.index.to_series().diff().dt.days / 365
    daily_ex = pd.DataFrame({e: par_return(yd[TENOR[e]], TENOR[e], dt) - yd["3M"].shift(1) * dt
                             for e in ETFS}).dropna()
    mom_vol = (daily_ex.ewm(com=MOM_EWM_COM, min_periods=MOM_EWM_COM).std() * np.sqrt(21)) \
        .resample("ME").last().to_period("M").reindex(excess.index)
    momentum_1_3_12 = sum(excess.rolling(h, min_periods=h).sum() / (mom_vol * np.sqrt(h))
                          for h in MOM_HORIZONS) / len(MOM_HORIZONS)

    return {"Carry": weighted_ma(rolling_z(to_etf(yld.sub(y3m, axis=0)), Z_WINDOW)),
            "Momentum": weighted_ma(momentum_1_3_12)}


# ── 4절: 비중 엔진 ──
def closest_to_equal(D, target):
    """25%씩에 가장 가까운 비중. 제약: 합 = 1, w·D = target, w ≥ 0 (음수가 나오면 SLSQP로 0에 고정)"""
    pref = np.full(len(D), 1 / len(D))
    C = np.vstack([np.ones_like(D), D])
    b = np.array([1.0, target])
    w = pref + C.T @ np.linalg.solve(C @ C.T, b - C @ pref)
    if (w >= -1e-12).all():
        return np.clip(w, 0.0, None)
    res = minimize(lambda x: ((x - pref) ** 2).sum(), x0=pref, jac=lambda x: 2 * (x - pref),
                   bounds=[(0.0, 1.0)] * len(D),
                   constraints=[{"type": "eq", "fun": lambda x: C @ x - b, "jac": lambda x: C}],
                   method="SLSQP", options={"ftol": 1e-12, "maxiter": 200})
    if not res.success:
        raise RuntimeError(f"비중 최적화 실패: {res.message}")
    return res.x


def max_lambda(N, A, D, lo, hi):
    """N + λA가 (비중 ≥ 0)과 (듀레이션 ∈ [lo, hi])를 만족하는 가장 큰 λ ∈ [0, 1]"""
    lam = 1.0
    neg = A < -1e-15
    if neg.any():
        lam = min(lam, float(np.min(N[neg] / -A[neg])))
    dA, dN = float(A @ D), float(N @ D)
    if dN + dA > hi:
        lam = min(lam, (hi - dN) / dA)
    elif dN + dA < lo:
        lam = min(lam, (lo - dN) / dA)
    return max(0.0, lam)


def decide(score, D, d_bbg):
    """한 달의 결정: ① 기본 비중 ② 수준 ③ 커브 ④ 합산 ⑤ 비례 축소. 중간값도 함께 돌려준다."""
    N = closest_to_equal(D, d_bbg)                                           # ① 기본 비중
    L = float(score.mean())
    dD = LEVEL_RANGE * float(np.clip(L / LEVEL_FULL, -1.0, 1.0))
    a_L = closest_to_equal(D, d_bbg + dD) - N                                # ② 수준 (합 0)
    a_C = CURVE_K * np.clip(score - L, -CURVE_CLIP, CURVE_CLIP)              # ③ 커브 (합 0)
    lam = max_lambda(N, a_L + a_C, D, d_bbg - BAND, d_bbg + BAND)            # ④ S = N + a_L + a_C, ⑤ 축소
    return {"w": N + lam * (a_L + a_C), "a_L": lam * a_L, "a_C": lam * a_C, "N": N,
            "λ": lam, "L": L, "ΔD": dD}


def build_style(score_df, duration, bbg_duration, months):
    """한 스타일의 월별 결정. w·a_L·a_C·N은 DataFrame, λ·L·ΔD는 Series (index = 결정 월)"""
    out = {k: {} for k in ["w", "a_L", "a_C", "N", "λ", "L", "ΔD"]}
    for t in months:
        if t not in score_df.index or t not in duration.index or t not in bbg_duration.index:
            continue
        x = score_df.loc[t, ETFS].to_numpy(float)
        D = duration.loc[t, ETFS].to_numpy(float)
        if np.isnan(x).any() or np.isnan(D).any() or pd.isna(bbg_duration.loc[t]):
            continue
        for k, v in decide(x, D, float(bbg_duration.loc[t])).items():
            out[k][t] = v
    res = {k: pd.DataFrame.from_dict(out[k], orient="index", columns=ETFS) for k in ["w", "a_L", "a_C", "N"]}
    res |= {k: pd.Series(out[k], dtype=float) for k in ["λ", "L", "ΔD"]}
    return res


def combine(parts):
    """여러 스타일 → 최종 비중(과 수준·커브 주문, λ)의 평균. L·ΔD는 스타일마다 달라 평균하지 않는다."""
    ix = parts[0]["w"].index
    for p in parts[1:]:
        ix = ix.intersection(p["w"].index)
    avg = lambda k: sum(p[k].loc[ix] for p in parts) / len(parts)
    res = {k: avg(k) for k in ["w", "a_L", "a_C", "N", "λ"]}
    if len(parts) == 1:
        res |= {"L": parts[0]["L"].loc[ix], "ΔD": parts[0]["ΔD"].loc[ix]}
    else:
        res |= {"L": pd.Series(np.nan, index=ix), "ΔD": pd.Series(np.nan, index=ix)}
    return res


def simulate(weights, etf_ret, duration, start, end, cost_bps=0.0):
    """T−1월 말 비중 → T월 보유. 양방향 회전율(드리프트 반영, 최초 편입 제외) × 편도 비용"""
    held = weights.set_axis(weights.index + 1)
    months = [m for m in held.index if start <= m <= end and m in etf_ret.index
              and etf_ret.loc[m, ETFS].notna().all()]
    rate = cost_bps / 1e4
    w_drift, rows = None, []
    for m in months:
        w = held.loc[m, ETFS].to_numpy(float)
        r = etf_ret.loc[m, ETFS].to_numpy(float)
        turnover = 0.0 if w_drift is None else np.abs(w - w_drift).sum()
        gross = float(w @ r)
        net = (1 - rate * turnover) * (1 + gross) - 1
        rows.append({"month": m, "gross": gross, "net": net, "turnover": turnover,
                     "duration": float(w @ duration.loc[m - 1, ETFS].to_numpy(float))})
        w_drift = w * (1 + r) / (1 + gross)
    cols = ["gross", "net", "turnover", "duration"]
    return pd.DataFrame(rows, columns=["month"] + cols).set_index("month")


def perf(bt, bench=None):
    """성과 지표 (Sharpe · Sortino rf = 0). bench가 있으면 초과수익·TE·IR"""
    r = bt["net"].dropna()
    if r.empty:
        return {}
    nav = (1 + r).cumprod()
    head = {"누적": nav.iloc[-1] - 1}
    if bench is not None:
        head["누적 초과"] = nav.iloc[-1] - (1 + bench["net"].reindex(r.index)).prod()
    if len(r) < 2:                          # 실운용 첫 달: 누적만
        return head
    years = len(r) / 12
    cagr = nav.iloc[-1] ** (1 / years) - 1
    mdd = (nav / nav.cummax().clip(lower=1.0) - 1).min()
    down = np.sqrt((np.minimum(r, 0) ** 2).mean()) * np.sqrt(12)
    out = head | {"CAGR": cagr, "σ": r.std(ddof=1) * np.sqrt(12),
           "Sharpe": r.mean() / r.std(ddof=1) * np.sqrt(12),
           "Sortino": r.mean() * 12 / down if down > 0 else np.nan,
           "MDD": mdd, "회전율/년": bt["turnover"].loc[r.index].sum() / years,
           "평균 D": bt["duration"].loc[r.index].mean()}
    if bench is not None:
        a = (r - bench["net"].reindex(r.index)).dropna()
        if len(a) >= 2:
            te = a.std(ddof=1) * np.sqrt(12)
            out |= {"초과수익/년": a.mean() * 12, "TE": te, "IR": a.mean() * 12 / te if te > 0 else np.nan}
    return out


def attribution(res, etf_ret):
    """수준 주문·커브 주문이 번 월 수익 (결정 월 주문 × 다음 달 수익)"""
    held = lambda df: df.set_axis(df.index + 1)
    R = etf_ret[ETFS]
    lv = (held(res["a_L"]) * R.reindex(held(res["a_L"]).index)).sum(axis=1, min_count=4)
    cv = (held(res["a_C"]) * R.reindex(held(res["a_C"]).index)).sum(axis=1, min_count=4)
    return pd.DataFrame({"수준": lv, "커브": cv}).dropna()
