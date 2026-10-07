# LCS 운용 대시보드

LCS-Carry 실운용 + Momentum·Carry+Momentum 모의 운용을 매달 추적하는 Streamlit 앱.

## 실행

`run_dashboard.bat`을 더블클릭하거나, 이 폴더에서:

```
streamlit run app.py
```

브라우저가 열리지 않으면 http://localhost:8501 로 접속.

## 매달 할 일 (월말 다음 영업일)

1. **Bloomberg에서 6개 값 가져오기** (그 달 마지막 영업일 기준)
   - OAD 5개: `LUATTRUU Index`, `I28478 Index`(SHY), `LT13STAT Index`(IEI), `LT09STAT Index`(IEF), `LT11STAT Index`(TLT)
   - `LUATTRUU Index` PX_LAST 1개
2. **④ 탭 → "Bloomberg 월말 값 입력"에 넣고 저장.** 전월보다 0.5년 넘게 변한 OAD, SPTB와 많이 다른 지수 수익률이 있으면 경고가 나옵니다.
   `inputs/bloomberg_monthly.csv`에 직접 한 줄 추가해도 같습니다.
3. **① 탭에서 이번 달 결정 확인 → 매매 목록대로 주문 → "결정 기록하기".**
4. **체결 후 ④ 탭 → "계좌 기록 입력"에 체결 내역 입력** (배당이 들어오면 세후 금액을 DIVIDEND로).

FRED 금리와 ETF 가격은 앱이 자동으로 받습니다 (6시간마다, 사이드바 버튼으로 즉시).

## 파일

| 파일 | 내용 | 누가 |
|---|---|---|
| `inputs/bloomberg_monthly.csv` | 월말 OAD 5개 + LUATTRUU 지수 값 | 팀이 매월 추가 |
| `inputs/trades.csv` | 입금·출금·매수·매도·배당 (USD) | 팀이 체결 후 추가 |
| `inputs/history/etf_tr_monthly.csv` | 백테스트에 쓴 Bloomberg ETF 총수익 지수 (~2026-08) | 고정 |
| `records/decision_log.csv` | 매달 확정한 결정 (점수·λ·비중) | 앱이 추가만 함, 수정 금지 |
| `cache/` | FRED·yfinance 수신 데이터 | 자동 (지워도 됨) |
| `config.py` | 실운용 시작월, 전략 규칙, Momentum 추가 조건 | 필요할 때 |
| `lcs_core.py` | 비중 엔진 (`LCS strategy.ipynb`와 같은 계산) | 노트북 규칙이 바뀌면 같이 |

## 데이터 규칙

- 신호는 **끝난 달**의 데이터로만 계산합니다. 그 달 마지막 영업일 값이 들어오기 전에는 이전 달 결정을 보여줍니다.
- ETF 월 수익률은 2026-08까지 Bloomberg 총수익 지수(백테스트와 동일), 2026-09부터 yfinance 수정주가입니다. 겹치는 기간의 차이는 ④ 탭 "ETF 수익률 출처 점검"에서 확인합니다.
- 성과 계산은 기록된 결정이 있는 달에는 기록된 비중을, 나머지는 다시 계산한 비중을 씁니다.
- 노트북 대비 검증 (2026-10-07): 2007-11 ~ 2026-08 Carry·Momentum 비중 차이 0, LCS-Carry Sharpe 0.59 · IR 0.22 · MDD −14.3%로 일치.

`setup_seed.py`는 최초 1회 노트북용 Bloomberg 파일을 입력 파일로 바꾸는 스크립트입니다. 다시 돌릴 필요 없습니다.
