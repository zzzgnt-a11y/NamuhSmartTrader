from __future__ import annotations

from pathlib import Path
import re

_INSTALLED = False


def apply(ns=None):
    global _INSTALLED
    if _INSTALLED:
        return True
    root = Path(__file__).resolve().parent

    # Only the strategy score composition UI is changed. No polling, charts,
    # budgets, page layout, refresh intervals, or other site variables are touched.
    try:
        p = root / "static" / "stock.html"
        text = p.read_text(encoding="utf-8")
        text = text.replace('<span class="v346-kicker">05 · SCORE MAP</span><h2>AI 점수 분해</h2>',
                            '<span class="v346-kicker">05 · SCORE MAP</span><h2>AI 점수 구성표</h2>')
        text = text.replace('<span class="v346-kicker">05 · SCORE MAP</span><h2>AI 분석 점수표</h2>',
                            '<span class="v346-kicker">05 · SCORE MAP</span><h2>AI 점수 구성표</h2>')
        text = text.replace("<small>점수 근거 확인</small>", "<small>조건1 · 조건2 · 조건3 구성</small>")
        text = text.replace("<small>조건1 · 조건2 · 조건3 상세</small>", "<small>조건1 · 조건2 · 조건3 구성</small>")
        p.write_text(text, encoding="utf-8")
    except Exception as exc:
        print("NAMUH SCOREBOARD HTML ERROR:", str(exc)[:180], flush=True)

    try:
        p = root / "static" / "stock.js"
        text = p.read_text(encoding="utf-8")
        new_fn = r'''function aiBar(label,value,max,meta=''){
 const n=num(value),mx=Math.max(1,num(max)),w=Math.max(0,Math.min(100,n/mx*100));
 return `<div class="ai-score-row"><div class="ai-score-line"><span>${esc(label)}</span><b>${n.toFixed(1)}/${mx}</b></div><div class="ai-score-bar"><i style="width:${w}%"></i></div>${meta?`<small>${esc(meta)}</small>`:''}</div>`
}
function aiGate(ok,label){return `<span class="ai-gate ${ok?'pass':'wait'}">${ok?'✓':'·'} ${esc(label)}</span>`}
function renderScores(d){
 const labels={'1m':'1분','3m':'3분','5m':'5분','20m':'20분','1d':'일봉'};
 $('scoreGrid').innerHTML=Object.entries(d.scores||{}).map(([k,v])=>`<div class="score-tile ${k===TF?'active':''}"><span>${labels[k]||esc(k)}</span><strong>${v==null?'—':num(v).toFixed(0)}</strong></div>`).join('')||'<div class="empty">AI 점수 축적 중</div>';
 const a=d.analysis;
 $('analysisReasons').innerHTML=a?(a.reasons||[]).slice(0,8).map(x=>`<span>${esc(x)}</span>`).join(''):'<div class="empty">해당 봉 기준 분석 데이터 축적 중</div>';
 const sc=d.strategy_conditions||{},c1=sc.condition1||{},b=c1.breakdown||{},g=c1.gates||{},raw=c1.standard_raw||{};
 const c2=sc.condition2||{},b2=c2.breakdown||{},m2=c2.market_1m||c2.kospi_1m||{};
 const c3=sc.condition3||{};
 if(!Object.keys(c1).length&&!Object.keys(c2).length&&!Object.keys(c3).length){
   const br=a?.breakdown||a?.components||{};
   $('breakdown').innerHTML=Object.entries(br).length?Object.entries(br).map(([k,v])=>aiBar(k,num(v),10)).join(''):'<div class="empty">전략 점수 데이터 축적 중</div>';
   return;
 }
 const ratio=c1.orderbook?.ratio;
 const c1html=`<section class="ai-condition-card primary">
   <div class="ai-condition-head"><div><small>CONDITION 1 · STANDARD</small><h3>조건1 구성표</h3></div><strong>${num(c1.score).toFixed(1)} / 100</strong></div>
   <div class="ai-stage"><h4>① 선행조건 · 40점</h4>
     ${aiBar('일봉',b.daily10,10,'현재가 > 전일 저가 + (전일 고가-저가)×0.5')}
     ${aiBar('분봉',b.minute10,10,'하락→저점 형성→직전 1분봉 고가 돌파 + 현재 양봉')}
     ${aiBar('체결강도',b.execution12,12,c1.execution_reason||'110↑ 즉시 / 90~110 50초·10초당 +0.5 / 90↓ 미진입')}
     ${aiBar('호가',b.orderbook8,8,ratio==null?'매도잔량÷매수잔량 수신 대기':`매도잔량÷매수잔량 ${num(ratio).toFixed(2)}배`)}
     <div class="ai-gates">${aiGate(g.daily,'일봉')}${aiGate(g.minute1m,'1분봉')}${aiGate(g.execution,'체결')}${aiGate(g.orderbook,'호가')}</div>
   </div>
   <div class="ai-down">↓</div>
   <div class="ai-stage"><h4>② 스탠다드 · 45점</h4>
     ${aiBar('스탠다드 기술지표',b.standard45,45,'원점수 75점을 45점으로 환산 · 엔벨로프 제외')}
     <div class="ai-c3-grid">
       <div><span>MACD</span><b>${num(raw.MACD).toFixed(1)}/10</b></div><div><span>RSI</span><b>${num(raw.RSI).toFixed(1)}/10</b></div>
       <div><span>볼린저</span><b>${num(raw['볼린저']).toFixed(1)}/10</b></div><div><span>거래량</span><b>${num(raw['거래량']).toFixed(1)}/15</b></div>
       <div><span>이동평균</span><b>${num(raw['이평']).toFixed(1)}/10</b></div><div><span>가격구조</span><b>${num(raw['가격구조']).toFixed(1)}/10</b></div>
       <div><span>엘리어트</span><b>${num(raw['엘리어트']).toFixed(1)}/10</b></div><div><span>환산</span><b>${num(b.standard45).toFixed(1)}/45</b></div>
     </div>
   </div>
   <div class="ai-down">↓</div>
   <div class="ai-stage"><h4>③ 추가가점 · 15점</h4>
     ${aiBar('섹터 상대강도',b.sector_relative7_5,7.5,'전체 섹터 대비 상대강도')}
     ${aiBar('주도섹터 수급',b.leading_sector_flow3_75,3.75,'주도섹터 수급 강도')}
     ${aiBar('뉴스 / 공시',b.news3_75,3.75,'호재 가점 · 중대 악재 진입 차단')}
   </div>
   <div class="ai-total-note">조건1 = 선행조건 40 + 스탠다드 45 + 추가가점 15 = 100점 · 총점 72점 이상 + 선행조건 통과</div>
 </section>`;
 const c2score=c2.score!=null?num(c2.score):num(sc.condition2_score);
 const c2html=`<section class="ai-condition-card">
   <div class="ai-condition-head"><div><small>CONDITION 2</small><h3>조건2 구성표</h3></div><strong>${c2score.toFixed(1)} / 100</strong></div>
   <div class="ai-stage"><h4>점수 구성 · 공통 선행조건 미적용</h4>
     ${aiBar('체결강도',b2.execution40,40,'진입 우선순위 1')}
     ${aiBar('호가',b2.orderbook25,25,'진입 우선순위 2')}
     ${aiBar('거래량',b2.volume25,25,'조건1 거래량 기준을 25점으로 환산')}
     ${aiBar('기술점수',b2.technical5,5,'조건1 스탠다드 기술점수를 5점으로 환산')}
     ${aiBar('등락률',b2.change5,5,c2.change_pct==null?'등락률 대기':`${num(c2.change_pct).toFixed(2)}%`)}
   </div>
   <div class="ai-gates wide">${aiGate(c2score>70,'총점 70 초과')}${aiGate(Boolean(m2.ready&&m2.up),`${esc(m2.market||'KOSPI')} 직전 완료 1분봉 상승`)}${aiGate(Boolean(c2.long_daily_ready),'장기 일봉 데이터 완료')}</div>
   <div class="ai-total-note">국장 매수 09:00~09:45 / 13:00~14:00 · 시간 외 점수상승 예외매수 없음 · 우선순위 체결 &gt; 호가 &gt; 거래량 &gt; 기술 &gt; 등락</div>
 </section>`;
 const c3html=`<section class="ai-condition-card">
   <div class="ai-condition-head"><div><small>CONDITION 3</small><h3>조건3 · 횡보 종목 진입형</h3></div><strong>${c3.gate?'진입대기':'감시'}</strong></div>
   <div class="ai-c3-grid">
     <div><span>국장 감시</span><b>09:00~10:00</b><small>오후 13:00~14:00 추가 감시</small></div>
     <div><span>횡보폭</span><b>3% 이상</b><small>동일 횡보구간 확인</small></div>
     <div><span>왕복 확인</span><b>2회 이상</b><small>최대 3종목 선정</small></div>
     <div><span>섹터</span><b>주도 TOP 3</b><small>현재 주도섹터 포함 필수</small></div>
     <div><span>국장 매수</span><b>10:30~13:00</b><small>오후 14:00~15:25</small></div>
     <div><span>매매 위치</span><b>하단 매수 → 상단 매도</b><small>횡보구간 최하단/최상단 기준</small></div>
   </div>
   <div class="ai-total-note">기존 2.7~3.3% 진입밴드 · 4.7% 목표 · AI 75점 조건은 사용하지 않음</div>
 </section>`;
 $('breakdown').innerHTML=`<div class="ai-scoreboard">${c1html}<div class="ai-condition-sep"></div>${c2html}<div class="ai-condition-sep"></div>${c3html}</div>`;
}'''
        pat = r"function renderScores\(d\)\{.*?\nfunction renderLiveFlow\(d\)\{"
        repl = new_fn + "\nfunction renderLiveFlow(d){"
        updated, n = re.subn(pat, repl, text, count=1, flags=re.S)
        if n != 1:
            print("NAMUH SCOREBOARD JS WARN: renderScores pattern not found", flush=True)
        else:
            p.write_text(updated, encoding="utf-8")
    except Exception as exc:
        print("NAMUH SCOREBOARD JS ERROR:", str(exc)[:180], flush=True)

    try:
        p = root / "static" / "v346.css"
        text = p.read_text(encoding="utf-8")
        marker = "/* NAMUH AI CONDITION SCOREBOARD */"
        if marker not in text:
            text += r'''

/* NAMUH AI CONDITION SCOREBOARD */
.ai-scoreboard{display:grid;gap:18px}.ai-condition-card{border:1px solid rgba(112,143,180,.22);border-radius:18px;padding:16px;background:rgba(9,22,39,.45)}
.ai-condition-card.primary{border-color:rgba(64,183,226,.34)}.ai-condition-head{display:flex;align-items:flex-end;justify-content:space-between;gap:12px;margin-bottom:14px}.ai-condition-head small{display:block;color:#59cbe8;font-weight:800;letter-spacing:.12em;font-size:10px}.ai-condition-head h3{margin:3px 0 0;font-size:21px}.ai-condition-head>strong{font-size:26px;color:#f4f8ff}
.ai-stage{display:grid;gap:10px}.ai-stage h4{margin:2px 0 0;font-size:13px;color:#c8d8eb}.ai-score-row{display:grid;gap:5px}.ai-score-line{display:flex;justify-content:space-between;gap:10px;font-size:12px}.ai-score-line span{font-weight:800;color:#dbe8f7}.ai-score-line b{color:#eef7ff}.ai-score-row>small{color:#8399b3;font-size:10px}.ai-score-bar{height:9px;border-radius:999px;background:rgba(124,148,178,.16);overflow:hidden}.ai-score-bar i{display:block;height:100%;border-radius:999px;background:linear-gradient(90deg,#32a9d5,#61d6b6)}
.ai-down{text-align:center;font-size:28px;line-height:1;padding:8px 0 6px;color:#6bc9e2}.ai-gates{display:flex;flex-wrap:wrap;gap:6px;margin-top:2px}.ai-gates.wide{margin-top:14px}.ai-gate{border-radius:999px;padding:5px 9px;font-size:10px;font-weight:800}.ai-gate.pass{background:rgba(32,180,132,.14);color:#70e4bb;border:1px solid rgba(32,180,132,.28)}.ai-gate.wait{background:rgba(236,176,69,.10);color:#d7ac66;border:1px solid rgba(236,176,69,.22)}.ai-total-note{margin-top:12px;padding-top:10px;border-top:1px solid rgba(112,143,180,.14);font-size:10px;color:#8399b3}
.ai-condition-sep{height:1px;background:rgba(112,143,180,.10)}.ai-c3-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:9px}.ai-c3-grid>div{padding:10px;border-radius:12px;background:rgba(18,35,56,.55);display:grid;gap:3px}.ai-c3-grid span{font-size:10px;color:#879bb4}.ai-c3-grid b{font-size:15px}.ai-c3-grid small{font-size:9px;color:#748ba7}
@media(max-width:720px){.ai-condition-card{padding:13px}.ai-condition-head>strong{font-size:22px}.ai-c3-grid{grid-template-columns:1fr}.ai-score-line{font-size:11px}}
'''
            p.write_text(text, encoding="utf-8")
    except Exception as exc:
        print("NAMUH SCOREBOARD CSS ERROR:", str(exc)[:180], flush=True)

    _INSTALLED = True
    print("NAMUH AI SCOREBOARD active: 구성표 C1 40/45/15 + C2 40/25/25/5/5 + C3 횡보형", flush=True)
    return True
