"""LCS 운용 대시보드 (Carry 실운용 + Momentum 모의 운용)

실행: 이 폴더에서  streamlit run app.py   (또는 run_dashboard.bat 더블클릭)
"""
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import config as C
import data
import lcs_core as core
import ledger

st.set_page_config(page_title="LCS 운용 대시보드", layout="wide")
PCT = ["누적", "누적 초과", "CAGR", "σ", "MDD", "초과수익/년", "TE", "회전율/년", "최악 36개월 초과 합"]
NUM = ["Sharpe", "Sortino", "IR", "평균 D"]


# ── 데이터와 모델 ──
def version():
    """입력 파일·캐시가 바뀌면 다시 계산하도록 수정 시각을 묶는다."""
    files = [C.BBG_FILE, C.TRADES_FILE, C.DECISION_LOG, C.ETF_TR_HISTORY,
             C.CACHE / "fred_daily.csv", C.CACHE / "prices_adj.csv"]
    return tuple(f.stat().st_mtime if f.exists() else 0 for f in files)


@st.cache_data(show_spinner="FRED · yfinance 데이터 준비 중…")
def load(ver):
    return data.assemble()


@st.cache_data(show_spinner="전략 계산 중…")
def run_model(ver, cost_bps):
    d = load(ver)
    scores = core.style_scores(d["fred"])
    last_dec = min(d["fred_done"], d["oad_done"])
    months = pd.period_range(C.START - 1, last_dec, freq="M")
    base = {s: core.build_style(scores[s], d["duration"], d["bbg_duration"], months) for s in ["Carry", "Momentum"]}
    strat = {n: core.combine([base[s] for s in parts]) for n, parts in C.STRATEGIES.items()}
    log = ledger.load_log()
    end = d["etf_ret"].dropna().index.max()
    runs = {n: core.simulate(ledger.with_log(n, strat[n]["w"], log), d["etf_ret"], d["duration"],
                             C.START, end, cost_bps) for n in strat}
    bench = {
        "Bloomberg UST": pd.DataFrame({"net": d["bbg_ret"], "turnover": 0.0,
                                       "duration": d["bbg_duration"].shift(1)}).loc[C.START:end],
        "Equal-weight": core.simulate(pd.DataFrame(0.25, index=months, columns=C.ETFS), d["etf_ret"],
                                      d["duration"], C.START, end, cost_bps),
        "SPTB": pd.DataFrame({"net": d["sptb_ret"], "turnover": 0.0, "duration": np.nan}).loc[C.START:end],
    }
    return {"scores": scores, "base": base, "strat": strat, "runs": runs, "bench": bench,
            "last_dec": last_dec, "end": end, "log": log}


def periods(end):
    p = {"전체": (C.START, end), "IS": (C.START, C.IS_END), "OOS": (C.OOS_START, end)}
    if C.LIVE_START <= end:
        p["실운용"] = (C.LIVE_START, end)
    return p


# ── 표·그림 도구 ──
def fmt(df):
    out = df.copy().astype(object)
    for c in df.columns:
        f = (lambda v: f"{v:.2%}") if c in PCT else (lambda v: f"{v:.2f}") if c in NUM else (lambda v: v)
        out[c] = [("—" if (isinstance(v, float) and np.isnan(v)) else f(v)) for v in df[c]]
    return out


def nav(r, a, b):
    s = (1 + r.loc[a:b].dropna()).cumprod()
    if s.empty:
        return s
    return pd.concat([pd.Series([1.0], index=[s.index[0] - 1]), s])


def x_of(ix):
    return ix.to_timestamp(how="end").normalize() if isinstance(ix, pd.PeriodIndex) else ix


def fig_base(title, ytitle, height=420):
    f = go.Figure()
    f.update_layout(title=dict(text=title, x=0, font=dict(size=15)), template="plotly_white", height=height,
                    hovermode="x unified", margin=dict(l=10, r=10, t=50, b=10), yaxis_title=ytitle,
                    legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="right", x=1))
    return f


def add_line(f, s, name, color, dash="solid", width=2, fmt_=".3f"):
    f.add_trace(go.Scatter(x=x_of(s.index), y=s.values, name=name, mode="lines",
                           line=dict(color=color, dash=dash, width=width), hovertemplate=f"%{{y:{fmt_}}}"))


def add_bench(f, s, name):
    color, dash = C.BENCH_COLORS[name]
    add_line(f, s, name, color, dash, 1.6)


def worst_36(a):
    """36개월 연속 구간 중 월 초과수익 합이 가장 나쁜 값 (발표 자료와 같은 정의)"""
    return a.rolling(36).sum().min() if len(a) >= 36 else np.nan


# ── 사이드바 ──
ver = version()
with st.sidebar:
    st.header("LCS 운용 대시보드")
    st.caption(f"실운용: **LCS-{C.LIVE_STRATEGY}** · 모의: Momentum, Carry+Momentum")
    cost = st.selectbox("편도 거래비용 (모델 성과)", C.COST_OPTIONS, format_func=lambda v: f"{v:g}bp",
                        help="0bp = 발표 기준, 10bp = 팀 가이드라인. 실제 계좌 성과에는 영향 없음")
    if st.button("FRED · yfinance 지금 다시 받기", use_container_width=True):
        with st.spinner("수신 중…"):
            data.fetch_fred(force=True)
            data.fetch_prices(force=True)
        st.cache_data.clear()
        st.rerun()

try:
    d = load(ver)
    M = run_model(ver, cost)
except Exception as e:
    st.error(f"데이터를 준비하지 못했습니다: {e}")
    st.stop()

with st.sidebar:
    st.markdown("**끝난 마지막 달**  \n" + "  \n".join(
        f"{r['데이터']}: {r['끝난 마지막 달']}" for _, r in d["status"].iterrows()))
    st.caption(f"자동 수신은 {C.CACHE_HOURS}시간마다 갱신. 실운용 시작 {C.LIVE_START} 보유분부터.")

tab1, tab2, tab3, tab4 = st.tabs(["① 이번 달 결정", "② 성과 추적", "③ Carry vs Momentum", "④ 데이터 입력·점검"])

# ════════════════════ ① 이번 달 결정 ════════════════════
with tab1:
    if d["fred_done"] > d["oad_done"]:
        st.warning(f"FRED 금리는 **{d['fred_done']}**까지 들어왔지만 **{d['fred_done']} OAD**가 아직 없습니다. "
                   f"④ 탭에서 입력하면 {d['fred_done']} 결정({d['fred_done'] + 1} 보유)이 계산됩니다.")
    dec_months = list(M["strat"][C.LIVE_STRATEGY]["w"].index[::-1])
    t = st.selectbox("결정 월 (이 달 말 신호 → 다음 달 보유)", dec_months[:36],
                     format_func=lambda m: f"{m} 결정 → {m + 1} 보유")
    D = d["duration"].loc[t, C.ETFS].to_numpy(float)
    D_B = float(d["bbg_duration"].loc[t])
    S = M["strat"]
    d_of = lambda n: float(S[n]["w"].loc[t].to_numpy(float) @ D)

    c = st.columns(5)
    c[0].metric("Bloomberg 지수 OAD", f"{D_B:.2f}년", help=f"한도 {D_B - C.BAND:.2f} ~ {D_B + C.BAND:.2f}년")
    c[1].metric(f"{C.LIVE_STRATEGY} 목표 듀레이션", f"{d_of('Carry'):.2f}년", f"{d_of('Carry') - D_B:+.2f}년 (지수 대비)",
                delta_color="off")
    c[2].metric("Carry 평균 점수 L", f"{S['Carry']['L'].loc[t]:+.2f}", help="±1이면 듀레이션 ±1.5년 이동")
    c[3].metric("Carry λ (실행 비율)", f"{S['Carry']['λ'].loc[t]:.2f}", help="1 = 판단 그대로, 1 미만 = 한도 때문에 축소")
    c[4].metric("Momentum 목표 듀레이션", f"{d_of('Momentum'):.2f}년", f"{d_of('Momentum') - D_B:+.2f}년 (지수 대비)",
                delta_color="off")

    bet_c, bet_m = d_of("Carry") - D_B, d_of("Momentum") - D_B
    same = np.sign(bet_c) == np.sign(bet_m)
    st.caption(("두 전략의 듀레이션 판단이 **같은 방향**입니다." if same else
                "두 전략의 듀레이션 판단이 **반대 방향**입니다. C+M에서는 서로 상쇄됩니다.")
               + f"  (Carry {bet_c:+.2f}년, Momentum {bet_m:+.2f}년)")

    left, right = st.columns([1.1, 1])
    with left:
        for n in ["Carry", "Momentum"]:
            sc = M["scores"][n].loc[t, C.ETFS]
            L = S[n]["L"].loc[t]
            tbl = pd.DataFrame({"점수": sc, "점수 − L": sc - L, "기본 비중 N": S[n]["N"].loc[t],
                                "수준 주문": S[n]["a_L"].loc[t], "커브 주문": S[n]["a_C"].loc[t],
                                "최종 비중": S[n]["w"].loc[t]}).T
            show = tbl.copy().astype(object)
            for r in tbl.index:
                show.loc[r] = [f"{v:+.2f}" if r in ["점수", "점수 − L"] else f"{v:.1%}" for v in tbl.loc[r]]
            st.markdown(f"**LCS-{n}**" + (" · 실운용" if n == C.LIVE_STRATEGY else " · 모의") +
                        f"  ·  L = {L:+.2f}, ΔD = {S[n]['ΔD'].loc[t]:+.2f}년, λ = {S[n]['λ'].loc[t]:.2f}")
            st.dataframe(show, use_container_width=True)
    with right:
        f = go.Figure()
        f.add_trace(go.Bar(x=C.ETFS, y=S["Carry"]["N"].loc[t].values * 100, name="기본 비중 N",
                           marker_color="#c3c2b7", hovertemplate="%{y:.1f}%"))
        for n in C.STRATEGIES:
            f.add_trace(go.Bar(x=C.ETFS, y=S[n]["w"].loc[t].values * 100, name=n, marker_color=C.COLORS[n],
                               hovertemplate="%{y:.1f}%"))
        f.update_layout(title=dict(text=f"{t + 1} 보유 비중 (%)", x=0, font=dict(size=15)), barmode="group",
                        template="plotly_white", height=380, bargap=0.25, bargroupgap=0.08,
                        margin=dict(l=10, r=10, t=50, b=10),
                        legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="right", x=1))
        st.plotly_chart(f, use_container_width=True)

    st.subheader(f"매매 목록 · LCS-{C.LIVE_STRATEGY}")
    trades = ledger.load_trades()
    shares_now, cash = ledger.positions(trades)
    px_date = d["close"][C.ETFS].dropna().index.max()
    price = d["close"].loc[px_date, C.ETFS]
    if trades.empty:
        cash = st.number_input("운용 금액 (USD) — 계좌 기록이 없어 직접 입력", min_value=0.0, value=0.0, step=1000.0)
    st.caption(f"현재 보유는 inputs/trades.csv 기준. 가격은 {px_date:%Y-%m-%d} 종가. 정수 주로 내림, 남는 돈은 현금.")
    if cash + float((shares_now * price).sum()) > 0:
        tl, nav_now, left_cash = ledger.trade_list(S[C.LIVE_STRATEGY]["w"].loc[t], shares_now, cash, price)
        show = tl.copy().astype(object)
        for col in tl.columns:
            show[col] = [f"{v:.1%}" if "비중" in col else f"{v:,.2f}" if col in ["가격", "매매 금액"] else f"{v:,.0f}"
                         for v in tl[col]]
        st.dataframe(show, use_container_width=True)
        st.caption(f"계좌 가치 {nav_now:,.2f} USD · 매매 후 남는 현금 {left_cash:,.2f} USD "
                   f"({left_cash / nav_now:.1%}) · 거래비용 미포함")

    st.subheader("결정 기록")
    log = M["log"]
    logged = (not log.empty) and (log["decision_month"] == t).any()
    if logged:
        sub = log[log["decision_month"] == t]
        st.success(f"{t} 결정은 {sub['recorded_at'].iloc[0]}에 기록되었습니다. 성과 계산에는 기록된 비중을 씁니다.")
        lw = ledger.logged_weights(C.LIVE_STRATEGY, log).loc[[t]]
        diff = (lw - M["strat"][C.LIVE_STRATEGY]["w"].loc[[t]]).abs().max().max()
        if diff > 1e-6:
            st.warning(f"지금 다시 계산한 비중과 기록이 최대 {diff:.2%}p 다릅니다 (입력 데이터가 바뀌었을 수 있음).")
    else:
        st.caption("매매를 실행할 결정을 확정하면 기록하세요. 기록은 추가만 되고, 나중에 데이터가 바뀌어도 그대로 남습니다.")
        if st.button(f"{t} 결정 기록하기 (Carry · Momentum · Carry+Momentum)", type="primary"):
            meta = {"fred_last_obs": str(d["fred_last"].date()), "oad_date": str(d["bbg"].loc[t, "date"].date()),
                    "D_bbg": D_B}
            rows = [ledger.log_row(n, t, S[n], M["scores"].get(n), D, meta) for n in C.STRATEGIES]
            k = ledger.record(rows)
            st.cache_data.clear()
            st.toast(f"{k}줄 기록했습니다.")
            st.rerun()

# ════════════════════ ② 성과 추적 ════════════════════
with tab2:
    P = periods(M["end"])
    c1, c2 = st.columns([1, 2])
    name = c1.radio("전략", list(C.STRATEGIES), horizontal=True, key="p_strat")
    per = c2.radio("구간", list(P), horizontal=True, key="p_per", index=len(P) - 1 if "실운용" in P else 0)
    a, b = P[per]
    bt, B = M["runs"][name], M["bench"]
    bb = B["Bloomberg UST"].loc[a:b]
    rows = {f"LCS-{name}": core.perf(bt.loc[a:b], bb), "Bloomberg UST": core.perf(bb),
            "Equal-weight": core.perf(B["Equal-weight"].loc[a:b], bb)}
    sptb = B["SPTB"].loc[a:b].dropna(subset=["net"])
    sptb_ok = len(sptb) and sptb.index.min() <= a
    if sptb_ok:
        rows["SPTB (ETF)"] = core.perf(sptb, bb)
    tbl = pd.DataFrame(rows).T.reindex(columns=["누적", "누적 초과", "CAGR", "σ", "Sharpe", "MDD", "초과수익/년", "TE",
                                                 "IR", "회전율/년", "평균 D"])
    st.markdown(f"**{per} ({a} ~ {b})** · Sharpe rf = 0 · 초과수익·TE·IR은 Bloomberg UST 대비 · 비용 {cost:g}bp")
    st.dataframe(fmt(tbl), use_container_width=True)
    if not sptb_ok:
        st.caption("SPTB는 2024-06부터 수익률이 있어, 그 이후에 시작하는 구간에서만 표시합니다.")

    f = fig_base(f"LCS-{name} 누적 순수익 (구간 시작 = 1)", "Growth of $1")
    add_bench(f, nav(bb["net"], a, b), "Bloomberg UST")
    add_bench(f, nav(B["Equal-weight"]["net"], a, b), "Equal-weight")
    if sptb_ok:
        add_bench(f, nav(sptb["net"], a, b), "SPTB")
    add_line(f, nav(bt["net"], a, b), f"LCS-{name}", C.COLORS[name], width=2.4)
    if a < C.LIVE_START <= b:
        f.add_vline(x=C.LIVE_START.to_timestamp(), line=dict(color="#52514e", dash="dash", width=1))
        f.add_annotation(x=C.LIVE_START.to_timestamp(), y=1, yref="paper", text="실운용 시작", showarrow=False,
                         xanchor="left", font=dict(size=11, color="#52514e"))
    st.plotly_chart(f, use_container_width=True)

    g1, g2 = st.columns(2)
    with g1:
        db = B["Bloomberg UST"]["duration"].loc[a:b]
        f = fig_base("보유 듀레이션 (OAD, 년) · 음영 = 지수 ± 1.5년", "years", 380)
        x = x_of(db.index)
        f.add_trace(go.Scatter(x=x, y=(db + C.BAND).values, line=dict(width=0), showlegend=False, hoverinfo="skip"))
        f.add_trace(go.Scatter(x=x, y=(db - C.BAND).values, line=dict(width=0), fill="tonexty",
                               fillcolor="rgba(42,120,214,0.10)", name="한도", hoverinfo="skip"))
        add_bench(f, db, "Bloomberg UST")
        add_line(f, bt["duration"].loc[a:b], f"LCS-{name}", C.COLORS[name], fmt_=".2f")
        st.plotly_chart(f, use_container_width=True)
    with g2:
        w = ledger.with_log(name, M["strat"][name]["w"], M["log"])
        w = w.set_axis(w.index + 1).loc[a:b]
        f = fig_base("자산별 비중 (%, 보유 월 기준)", "%", 380)
        for e in C.ETFS:
            f.add_trace(go.Scatter(x=x_of(w.index), y=w[e].values * 100, name=e, stackgroup="w", mode="lines",
                                   line=dict(width=0.5, color="#fcfcfb"), fillcolor=C.W_COLORS[e],
                                   hovertemplate="%{y:.1f}%"))
        f.update_yaxes(range=[0, 100])
        st.plotly_chart(f, use_container_width=True)

    att = core.attribution(M["strat"][name], d["etf_ret"]).loc[a:b]
    lam = M["strat"][name]["λ"]
    lam = lam.set_axis(lam.index + 1).loc[a:b]
    st.markdown("**스타일 판단의 기여** (결정 월 주문 × 다음 달 수익, 연율, 다시 계산한 비중 기준)")
    st.dataframe(pd.DataFrame({"수준 기여/년": f"{att['수준'].mean() * 12:+.2%}",
                               "커브 기여/년": f"{att['커브'].mean() * 12:+.2%}",
                               "합계/년": f"{(att['수준'] + att['커브']).mean() * 12:+.2%}",
                               "평균 λ": f"{lam.mean():.2f}"}, index=[per]), use_container_width=True)

    st.subheader("실제 계좌")
    trades = ledger.load_trades()
    acc = ledger.account_monthly(trades, d["close"])
    if not acc.empty:
        acc = acc.loc[C.LIVE_START:d["price_done"]]
    if acc.empty:
        st.info("inputs/trades.csv(④ 탭)에 입금·체결 내역을 넣으면 실제 계좌 성과와 모델과의 차이가 표시됩니다.")
    else:
        model = M["runs"][C.LIVE_STRATEGY]["net"]
        cmp = pd.DataFrame({"계좌": acc["ret"], f"모델 LCS-{C.LIVE_STRATEGY}": model.reindex(acc.index),
                            "Bloomberg UST": M["bench"]["Bloomberg UST"]["net"].reindex(acc.index)})
        cmp["실행 차이 (계좌 − 모델)"] = cmp["계좌"] - cmp[f"모델 LCS-{C.LIVE_STRATEGY}"]
        cmp["월말 계좌 가치"] = acc["nav"]
        show = cmp.copy().astype(object)
        for col in cmp.columns:
            show[col] = [("—" if pd.isna(v) else f"{v:,.2f}" if col == "월말 계좌 가치" else f"{v:+.2%}") for v in cmp[col]]
        st.dataframe(show, use_container_width=True)
        tot = (1 + cmp[["계좌", f"모델 LCS-{C.LIVE_STRATEGY}", "Bloomberg UST"]]).prod() - 1
        st.caption(f"{C.LIVE_START}부터 누적: 계좌 {tot.iloc[0]:+.2%} · 모델 {tot.iloc[1]:+.2%} · Bloomberg UST {tot.iloc[2]:+.2%}. "
                   "실행 차이 = 정수 주 반올림 · 체결가 · 수수료 · 남는 현금 · 배당 입력 시점. 원화 환산은 하지 않음 (USD).")

# ════════════════════ ③ Carry vs Momentum ════════════════════
with tab3:
    st.caption("Carry는 실운용, Momentum과 Carry+Momentum은 같은 규칙으로 매달 계산만 하는 모의 운용입니다. "
               "발표에서 C+M의 근거로 든 세 가지(듀레이션 판단 상관, 추적오차, Carry 손실 상쇄)를 계속 확인합니다.")
    P = periods(M["end"])
    per3 = st.radio("구간", list(P), horizontal=True, key="cm_per")
    a, b = P[per3]
    bb = M["bench"]["Bloomberg UST"].loc[a:b]
    R = {n: M["runs"][n].loc[a:b] for n in C.STRATEGIES}
    EX = {n: (R[n]["net"] - bb["net"].reindex(R[n].index)).dropna() for n in R}

    rows = {}
    for n in C.STRATEGIES:
        p = core.perf(R[n], bb)
        rows[f"LCS-{n}"] = p | {"최악 36개월 초과 합": worst_36(EX[n])}
    tbl = pd.DataFrame(rows).T.reindex(columns=["누적", "CAGR", "Sharpe", "MDD", "초과수익/년", "TE", "IR",
                                                 "최악 36개월 초과 합", "회전율/년"])
    st.dataframe(fmt(tbl), use_container_width=True)

    bets = pd.DataFrame({n: R[n]["duration"] - bb["duration"].reindex(R[n].index) for n in ["Carry", "Momentum"]})
    loss = EX["Carry"] < 0
    k = st.columns(4)
    k[0].metric("듀레이션 판단 상관", f"{bets.corr().iloc[0, 1]:.2f}",
                help="보유 듀레이션 − 지수 OAD의 월별 상관. 낮을수록 두 판단이 서로 다름")
    k[1].metric("추적오차 C+M / Carry", f"{tbl.loc['LCS-Carry+Momentum', 'TE']:.2%} / {tbl.loc['LCS-Carry', 'TE']:.2%}")
    avg_in_loss = lambda n: f"{EX[n].reindex(loss[loss].index).mean():+.2%}" if loss.any() else "—"
    k[2].metric("Carry 손실 달의 Momentum", avg_in_loss("Momentum"),
                help=f"Carry 초과수익이 음수였던 {int(loss.sum())}개월의 Momentum 평균 월 초과수익")
    k[3].metric("같은 달 C+M (아래: Carry)", avg_in_loss("Carry+Momentum"),
                avg_in_loss("Carry") if loss.any() else None, delta_color="off",
                help="Carry 손실 달의 C+M 평균 월 초과수익. 아래 작은 숫자는 Carry 자신")

    f = fig_base("누적 순수익 (구간 시작 = 1)", "Growth of $1")
    add_bench(f, nav(bb["net"], a, b), "Bloomberg UST")
    for n in C.STRATEGIES:
        add_line(f, nav(R[n]["net"], a, b), f"LCS-{n}", C.COLORS[n], width=2.4 if n == C.LIVE_STRATEGY else 1.8)
    st.plotly_chart(f, use_container_width=True)

    g1, g2 = st.columns(2)
    with g1:
        f = fig_base("듀레이션 판단 (보유 듀레이션 − 지수 OAD, 년)", "years", 380)
        for n in ["Carry", "Momentum"]:
            add_line(f, bets[n], n, C.COLORS[n], width=1.6, fmt_="+.2f")
        f.add_hline(y=0, line=dict(color="#52514e", width=1))
        st.plotly_chart(f, use_container_width=True)
    with g2:
        f = fig_base("36개월 롤링 초과수익 (연율, Bloomberg UST 대비)", "%/년", 380)
        for n in C.STRATEGIES:
            add_line(f, EX[n].rolling(36).mean() * 1200, n, C.COLORS[n], width=1.6, fmt_="+.2f")
        f.add_hline(y=0, line=dict(color="#52514e", width=1))
        st.plotly_chart(f, use_container_width=True)
        if len(EX["Carry"]) < 36:
            st.caption("구간이 36개월보다 짧아 롤링 값이 없습니다. '전체' 구간에서 확인하세요.")

    st.markdown("**Momentum 실운용 추가 조건**")
    if C.MOMENTUM_REVIEW_RULE:
        st.info(C.MOMENTUM_REVIEW_RULE)
    else:
        st.warning("미정. 결과를 보기 전에 팀이 정해 config.py의 MOMENTUM_REVIEW_RULE에 적어 두세요 "
                   "(예: 운용 N개월 후 어떤 지표가 어떤 값이면 추가).")

# ════════════════════ ④ 데이터 입력·점검 ════════════════════
with tab4:
    st.subheader("데이터 상태")
    st.dataframe(d["status"].astype(str), hide_index=True, use_container_width=True)
    st.caption("끝난 마지막 달 = 그 달 마지막 영업일 값까지 들어온 달. 신호는 끝난 달의 데이터로만 계산합니다.")

    st.subheader("Bloomberg 월말 값 입력")
    bbg = d["bbg"]
    next_m = d["oad_done"] + 1
    prev = bbg.dropna(subset=data.BBG_COLS[:5]).iloc[-1]
    st.caption(f"다음에 넣을 달: **{next_m}** · 괄호 안은 전월({prev.name}) 값 · "
               "파일로 직접 넣어도 됩니다: inputs/bloomberg_monthly.csv")
    with st.form("bbg_form"):
        date = st.date_input("기준일 (그 달 마지막 영업일)", value=data.last_bday(next_m).date())
        cols = st.columns(3)
        vals = {}
        for i, col in enumerate(data.BBG_COLS):
            pv = prev[col]
            vals[col] = cols[i % 3].number_input(f"{data.BBG_LABELS[col]}  ({pv:,.4f})" if pd.notna(pv)
                                                 else data.BBG_LABELS[col], value=None, format="%.6f",
                                                 min_value=0.0, key=f"bbg_{col}")
        ok_warn = st.checkbox("경고가 나와도 값을 확인했으니 저장")
        if st.form_submit_button("검사 후 저장", type="primary"):
            row = {"date": pd.Timestamp(date)} | {k: (np.nan if v is None else float(v)) for k, v in vals.items()}
            errors, warns = data.check_bbg_row(row, bbg, d["sptb_ret"])
            for e in errors:
                st.error(e)
            for w_ in warns:
                st.warning(w_)
            if not errors and (not warns or ok_warn):
                data.append_bbg(row)
                st.cache_data.clear()
                st.success(f"{pd.Timestamp(date).to_period('M')} 값을 저장했습니다.")
                st.rerun()
            elif not errors:
                st.info("경고를 확인했다면 위 체크박스를 켜고 다시 저장하세요.")
    with st.expander("최근 입력 값 (12개월)"):
        st.dataframe(bbg.tail(12).assign(date=lambda x: x["date"].dt.date), use_container_width=True)

    st.subheader("계좌 기록 입력")
    st.caption("입금(DEPOSIT)·출금(WITHDRAW)은 amount, 매수(BUY)·매도(SELL)는 ticker·shares·price·fee, "
               "배당(DIVIDEND)은 세후 입금액을 amount에. 모두 USD. 파일: inputs/trades.csv")
    with st.form("trade_form"):
        c = st.columns(4)
        t_date = c[0].date_input("날짜")
        t_type = c[1].selectbox("종류", list(ledger.TRADE_TYPES), format_func=lambda k: f"{k} ({ledger.TRADE_TYPES[k]})")
        t_tick = c[2].selectbox("종목", [""] + C.ETFS)
        t_sh = c[3].number_input("수량 (주)", min_value=0.0, step=1.0)
        c = st.columns(4)
        t_px = c[0].number_input("체결가 (USD)", min_value=0.0, format="%.4f")
        t_fee = c[1].number_input("수수료 (USD)", min_value=0.0, format="%.2f")
        t_amt = c[2].number_input("금액 (입출금·배당, USD)", min_value=0.0, format="%.2f")
        t_memo = c[3].text_input("메모")
        if st.form_submit_button("기록 추가"):
            bad = (t_type in ["BUY", "SELL"] and (not t_tick or t_sh <= 0 or t_px <= 0)) or \
                  (t_type in ["DEPOSIT", "WITHDRAW", "DIVIDEND"] and t_amt <= 0)
            if bad:
                st.error("매수·매도는 종목·수량·체결가, 입출금·배당은 금액이 필요합니다.")
            else:
                ledger.append_trade({"date": t_date, "type": t_type, "ticker": t_tick, "shares": t_sh,
                                     "price": t_px, "fee": t_fee, "amount": t_amt, "memo": t_memo})
                st.cache_data.clear()
                st.rerun()
    tr = ledger.load_trades()
    if not tr.empty:
        st.dataframe(tr.assign(date=tr["date"].dt.date), hide_index=True, use_container_width=True)
        sh, ca = ledger.positions(tr)
        st.caption("현재 보유: " + ", ".join(f"{e} {int(v)}주" for e, v in sh.items() if v) + f" · 현금 {ca:,.2f} USD")

    st.subheader("점수 추이")
    f = fig_base("평균 점수 L (결정 월) · ±1이면 듀레이션 ±1.5년", "L", 360)
    for n in ["Carry", "Momentum"]:
        add_line(f, M["strat"][n]["L"].loc["2015-01":], n, C.COLORS[n], width=1.6, fmt_="+.2f")
    for y in [-1, 1]:
        f.add_hline(y=y, line=dict(color="#c3c2b7", dash="dot", width=1))
    st.plotly_chart(f, use_container_width=True)

    st.subheader("ETF 수익률 출처 점검")
    ov = d["yf_ret"].loc[:"2026-08"].tail(12)
    hist = d["etf_ret"].reindex(ov.index)
    st.caption("백테스트 구간은 Bloomberg 총수익 지수, 2026-09부터는 yfinance 수정주가를 씁니다. "
               "겹치는 최근 12개월의 월 수익률 차이 (yfinance − Bloomberg, %p):")
    st.dataframe(((ov - hist) * 100).round(3).rename(index=str).T, use_container_width=True)

    st.subheader("결정 기록")
    if M["log"].empty:
        st.caption("아직 기록이 없습니다. ① 탭에서 결정을 기록하세요.")
    else:
        st.dataframe(M["log"].astype({"decision_month": str}), hide_index=True, use_container_width=True)
