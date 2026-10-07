"""LCS 대시보드 설정.

전략 규칙 숫자(Z_WINDOW ~ BAND)는 `LCS strategy.ipynb` 1절과 반드시 같아야 한다.
노트북에서 바꾸면 여기도 같이 바꾼다.
"""
from pathlib import Path

import pandas as pd

# ── 파일 위치 ──
HERE = Path(__file__).resolve().parent
INPUTS = HERE / "inputs"            # 팀이 직접 채우는 파일
RECORDS = HERE / "records"          # 매달 확정한 결정 기록 (추가만, 수정 금지)
CACHE = HERE / "cache"              # FRED · yfinance 자동 수신 (지워도 다시 받음)

BBG_FILE = INPUTS / "bloomberg_monthly.csv"            # 매월 말 OAD 5개 + LUATTRUU 지수 값
TRADES_FILE = INPUTS / "trades.csv"                    # 실제 계좌 입출금·체결·배당
ETF_TR_HISTORY = INPUTS / "history" / "etf_tr_monthly.csv"   # 백테스트에 쓴 Bloomberg ETF 총수익 지수 (2026-08까지)
DECISION_LOG = RECORDS / "decision_log.csv"

# ── 자산 ──
ETFS = ["SHY", "IEI", "IEF", "TLT"]
TENOR = {"SHY": 2, "IEI": 5, "IEF": 10, "TLT": 20}
BENCH_ETF = "SPTB"                  # Bloomberg US Treasury Index 추종 ETF (2024-05 상장), 참고용 벤치마크
FRED_SERIES = {2: "DGS2", 5: "DGS5", 10: "DGS10", 20: "DGS20", "3M": "DGS3MO"}
PRICE_START = "2002-07-01"
CACHE_HOURS = 6                     # 자동 수신 데이터를 다시 받는 주기

# ── 기간 ──
START = pd.Period("2007-11", "M")    # 백테스트 첫 보유 월
IS_END, OOS_START = pd.Period("2022-12", "M"), pd.Period("2023-01", "M")
LIVE_START = pd.Period("2026-10", "M")   # 실운용 첫 보유 월 (2026-09 말 신호 → 10월 보유)

# ── 전략 규칙 (노트북과 동일) ──
Z_WINDOW = 120
MOM_HORIZONS = [1, 3, 12]
MOM_EWM_COM = 60
LEVEL_RANGE = 1.5
LEVEL_FULL = 1.0
CURVE_K = 0.15
CURVE_CLIP = 2.0
BAND = 1.5
COST_OPTIONS = [0.0, 10.0]          # 편도 거래비용 (bp). 노트북 발표 기준 0, 팀 가이드라인 10

STRATEGIES = {                      # 대시보드가 추적하는 전략 → 구성 스타일 (여러 개면 최종 비중의 평균)
    "Carry": ["Carry"],
    "Momentum": ["Momentum"],
    "Carry+Momentum": ["Carry", "Momentum"],
}
LIVE_STRATEGY = "Carry"             # 실제 돈이 들어가는 전략. 나머지는 모의 운용

# Momentum을 실운용에 추가할 조건. 결과를 보기 전에 팀이 정해서 적어 둔다 (빈칸이면 "미정"으로 표시)
MOMENTUM_REVIEW_RULE = ""

# ── 입력 검증 ──
OAD_JUMP_WARN = 0.5                 # 전월 대비 OAD 변화가 이보다 크면 경고 (년)
BBG_VS_SPTB_WARN = 0.005            # LUATTRUU 월 수익률과 SPTB 월 수익률 차이가 이보다 크면 경고

# ── 색 (노트북과 같은 팔레트) ──
COLORS = {"Carry": "#1baf7a", "Momentum": "#eb6834", "Carry+Momentum": "#2a78d6"}
W_COLORS = {"SHY": "#86b6ef", "IEI": "#3987e5", "IEF": "#256abf", "TLT": "#104281"}
BENCH_COLORS = {"Bloomberg UST": ("#0b0b0b", "dot"), "Equal-weight": ("#52514e", "dash"),
                "SPTB": ("#8a8984", "dashdot")}
