NamuhSmartTrader v34 통합 수정

업로드할 파일:
- runtime_server_v34.py  (repo 루트)
- render.yaml            (repo 루트, 기존 파일 교체)
- static/v34.js
- static/coin-v34.js
- static/coin-detail-v34.js
- static/stock-v34.js
- static/tooltip-v34.js
- static/v34.css

Render는 render.yaml 기준으로 `python runtime_server_v34.py`를 실행하고
health check는 `/api/v34/status`를 사용합니다.

v34 주요 규칙:
- 상단 AUTO ON/OFF는 신규 진입만 제어. 보유 포지션 청산 관리는 계속.
- 손익 표시는 실현손익만. 보유 평가손익은 EQUITY에는 반영되지만 수익에는 미포함.
- 주식 캘린더: KR+US 통합, KST 00:00 기준 SELL 실현손익만.
- 코인 캘린더: 주식과 분리, 동일하게 KST 00:00 기준 SELL 실현손익만.
- KR 이상수급: 직전 5거래일 평균 거래량을 1분 기대량으로 환산해 최근 1분 거래량 급증,
  체결강도 급상승, 최근 5개 1분봉 상승추세를 핵심 70점으로 사용.
  외국인/기관/연기금(피드 제공 시)/프로그램 매수는 보조 가점 30점.
  최대 3개, 60초 노출, 알림 종목은 우선 분석하되 기존 진입 기준을 우회하지 않음.
- KR/US 공시 이벤트: +5 / 0 / -5, 중대 악재는 신규진입 차단.
- 모든 주식 신규진입은 최근 5개 1분봉 상승추세 확인 후 허용.
- US 공시는 SEC EDGAR public feed 사용. SEC_USER_AGENT는 Render 환경변수로 바꿀 수 있음.
- 코인: VALUE SCORE 30 + TECHNICAL SCORE 70 = TOTAL 100.
  VALUE raw100 = 거래대금순위10 + 체결강도20 + 단기모멘텀20 + 거래량가속15 + 호가매수우위15 + 추세10 + 매수·매도가격차5 + 변동성5.
  TECHNICAL raw85 = MACD10 + RSI10 + 볼린저10 + 이평10 + Williams%R10 + 엘리어트10 + 거래량15 + 가격구조10, 이후 70점으로 환산.
- 코인 UI는 거래대금 상위 8개 / 단타 후보 8개만 표시(내부 분석 범위는 더 넓게 유지).
