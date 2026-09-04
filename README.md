# Namuh Smart Trader v1.0 WEB

앱 설치 대신 **폰 브라우저에서 링크 하나로 보는 AI 모의투자 사이트**입니다.

## 핵심
- 실제 NH Namuh PLUG KRX 데이터 → AI 규칙엔진 → 가상 100만원 PAPER 거래
- 실제 증권사 주문 코드 없음 (`orders_sent = 0`)
- 1. 단타 / 2. 스마트머니 / 3. 오늘 매매
- 오늘 운용금액 저장 및 동시 보유원가 한도
- 기존 실보유 종목은 `PROTECTED_CODES`로 제외
- 종목 상세: 현재가 / PER / PBR / 상승 VI 직전 참고가 / 가격 그래프
- KRX ONLY, NXT 제외
- 모바일 최적화 사이트. Android Chrome에서 "홈 화면에 추가"하면 앱처럼 사용 가능

## 배포: Render
1. GitHub에 이 프로젝트 전체 업로드
2. Render → New → Blueprint
3. 저장소 연결 → `render.yaml` 자동 인식
4. `NHPLUG_APP_KEY`, `NHPLUG_APP_SECRET` 입력
5. Deploy
6. 생성된 `https://...onrender.com` 주소를 폰에서 열기

## 실시간 상태에 관한 중요 사항
국내 종목 AI PAPER는 공식 NHPLUG KRX 현재가/실시간 채널을 사용합니다.
첫 화면의 KOSPI/KOSDAQ/야간선물/NASDAQ/SOX/NASDAQ선물 카드는 **가짜 값을 만들지 않습니다**.
각 공식 NH 지수/파생 채널의 상품코드와 이용권한을 E2E 확인하기 전에는 '연결 필요'로 표시됩니다.
이 값을 임의의 Yahoo/스크래핑 값으로 '실시간'이라고 표시하지 않습니다.

## 기본 PAPER 룰
- 초기 가상자금 1,000,000원
- 기본 일일 운용한도 200,000원
- 단타 AI 점수 72 이상 신규매수
- +2.5% 익절 / -1.5% 손절 / 점수 46 미만 매도
- 최대 동시 3종목
- 상승 VI 직전 참고가 이상 신규매수 금지
- 매도하면 운용한도 재사용 가능
