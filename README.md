# Namuh Smart Trader v0.4 — LIVE AI PAPER

목표: **실제 시장 데이터를 보고 AI 규칙엔진이 가상 100만원으로 자동 매수/매도**하고,
Android 앱에서 실시간으로 확인합니다. 실제 증권사 주문은 이 버전에서 0건입니다.

## 반영된 사용자 요구
- 메뉴 1: 오늘 급수급/단타
  - MACD, RSI, Williams %R, 5/10/20 이평, 거래량, 체결강도, DMI, 볼린저, 골든구조
  - KRX ONLY / NXT 제외
  - 장 시작가 → 상승 VI 직전 가격 범위
  - 현재 PAPER 보유종목을 리스트 위에 표시
- 메뉴 2: 스마트머니 + PER/PBR 저평가
  - 외국인/기관 수급, 누적흐름, PER/PBR 저평가
- 메뉴 3: 오늘 매수/매도, 수익률/손익금
- 첫 화면: KOSPI/KOSDAQ/야간선물/NASDAQ/SOX/NASDAQ선물 + 그래프 자리 + 오늘 주도섹터
- 종목 상세: 현재가/PER/PBR/상승VI/그래프
- 오늘 운용금액 저장
  - 보유 PAPER 매입원가 합이 한도에 도달하면 추가매수 차단
  - 매도 후 다시 매수 가능
- 기존 실제 보유종목은 보호코드로 AI 후보에서 제외
- 세련된 카드형 UI + 자체 귀여운 마스코트 톤
- 가상 초기자금: 1,000,000원

## 실시간 구조
Android APK에는 NH 앱키/시크릿을 넣지 않습니다.

`NHPLUG KRX WebSocket → Python Live Backend → Android 1.5초 갱신 → AI PAPER 엔진`

국내주식 현재가 초기 시드는 공식 NHPLUG REST `/krstock/quote/v1/currentPrice`,
실시간은 공식 Python SDK `nhplug.realtime.subscribe()`를 사용합니다.

### 중요한 NH WebSocket 한도
NH PLUG 실시간은 앱키당 동시 세션/세션당 등록 건수에 제한이 있으므로
전 종목 수천 개를 한 연결에서 틱 단위로 구독하는 구조는 불가능합니다.
v0.4는 공식 종목마스터를 읽어 **KRX 전 종목을 REST 호출한도에 맞춰 순환 스캔**하고, 급수급 상위 후보를 **WebSocket tick 실시간**으로 자동 승격합니다. 따라서 후보의 체결가는 실시간이지만 전 종목의 '발견 지연'은 전체 스캔 한 바퀴 시간만큼 존재합니다. 전 종목 수천 개를 모두 동시에 WebSocket 구독하는 방식은 제공 한도상 사용하지 않습니다.

## 실행
1. `backend/.env.example` → `backend/.env` 복사
2. `NHPLUG_APP_KEY`, `NHPLUG_APP_SECRET` 입력
3. `START_LIVE_BACKEND.bat`
4. Android 앱 → `연결설정` → 서버 주소 입력
5. AI 자동 모의매매 체크

같은 Wi-Fi에서 PC 서버를 쓸 경우 서버 PC의 내부 IP 예:
`http://192.168.0.10:8787`

## 안전
- 이 버전에는 실제 매수/매도 주문 API 호출 코드가 없습니다.
- PAPER 체결만 로컬 앱에서 기록합니다.
- 실계좌 보호종목은 `PROTECTED_CODES=005930,...` 로 지정할 수 있습니다.
- 해외/시장 대시보드의 Yahoo fallback은 지연 가능하며 **AI 매매 신호에는 사용하지 않습니다.**
- 국내 AI 판단 가격은 NHPLUG KRX 실시간 피드만 사용합니다.
