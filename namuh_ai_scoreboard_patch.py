from __future__ import annotations

from pathlib import Path
import re

_INSTALLED = False


def apply(ns=None):
    global _INSTALLED
    if _INSTALLED:
        return True
    root = Path(__file__).resolve().parent

    try:
        p = root / "static" / "stock.html"
        text = p.read_text(encoding="utf-8")
        text = text.replace("<span class=\"v346-kicker\">05 · SCORE MAP</span><h2>AI 점수 분해</h2>",
                            "<span class=\"v346-kicker\">05 · SCORE MAP</span><h2>AI 분석 점수표</h2>")
        text = text.replace("<small>점수 근거 확인</small>", "<small>조건1 · 조건2 · 조건3 상세</small>")
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
 const sc=d.strategy_conditions||{},c1=sc.condition1||{},b=c1.breakdown||{},g=c1.gates||{};
 const c2=sc.condition2||{},f2=c2.front60||{},k2=c2.kospi_1m||c2.market_1m||{},m2=c2.monthly_discount||{};
 const c3=sc.condition3||{};
 if(!Object.keys(c1).length&&!Object.keys(c2).length&&!Object.keys(c3).length){
   const br=a?.breakdown||a?.components||{};
   $('breakdown').innerHTML=Object.entries(br).length?Object.entries(br).map(([k,v])=>aiBar(k,num(v),10)).join(''):'<div class="empty">전략 점수 데이터 축적 중</div>';
   return;
 }
 const c1html=`<section class="ai-condition-card primary">
   <div class="ai-condition-head"><div><small>CONDITION 1</small><h3>조건1</h3></div><strong>${num(c1.score).toFixed(1)}점</strong></div>
   <div class="ai-stage"><h4>진입 조건</h4>
     ${aiBar('일봉',b.daily20,20,g.daily?'통과':'기준 8/20 이상 필요')}
     ${aiBar('1분봉',b.minute20,20,g.minute1m?'통과':'완료 1분봉 기준 10/20 이상 필요')}
     ${aiBar('체결강도',b.execution20,20,c1.execution_reason||'체결강도 인터락')}
     <div class="ai-gates">${aiGate(g.daily,'일봉')}${aiGate(g.minute1m,'1분봉')}${aiGate(g.execution,'체결강도')}</div>
   </div>
   <div class="ai-down">↓</div>
   <div class="ai-stage"><h4>구매 확정 조건</h4>
     ${aiBar('기술지표 종합',b.technical25,25,'MACD · RSI · 볼린저 · 이평 · 가격구조 종합')}
     <div class="ai-gates">${aiGate(g.technical,'기술지표')}</div>
   </div>
   <div class="ai-down">↓</div>
   <div class="ai-stage"><h4>추가 가점 조건</h4>
     ${aiBar('주도섹터',b.leading_sector5,5,c1.leading_sector_rank?`섹터 ${c1.leading_sector_rank}위`:'' )}
     ${aiBar('섹터내 수급',b.sector_inner_flow5,5,c1.sector_inner_flow_rank?`섹터내 수급 ${c1.sector_inner_flow_rank}/${c1.sector_peer_count||'-'}위`:'' )}
     ${aiBar('공시 및 뉴스',b.news5,5,'호재 가점 · 중대 악재는 진입 차단')}
   </div>
   <div class="ai-total-note">총점 72점 이상 + 진입/구매확정 인터락 통과 시 조건1 활성</div>
 </section>`;
 const c2score=c2.score!=null?num(c2.score):num(sc.condition2_score);
 const c2html=`<section class="ai-condition-card">
   <div class="ai-condition-head"><div><small>CONDITION 2</small><h3>조건2</h3></div><strong>${c2score.toFixed(1)}점</strong></div>
   <div class="ai-stage"><h4>점수 구성</h4>
     ${aiBar('거래량',f2.volume20,20,'장중 거래량 속도')}
     ${aiBar('체결강도',f2.execution20,20,'체결강도')}
     ${aiBar('등락률',f2.change20,20,f2.change_pct!=null?`전일 종가 대비 ${num(f2.change_pct).toFixed(2)}%`:'' )}
     ${aiBar('기술지표',c2.technical40,40,'기술지표 비중을 크게 보는 조건')}
   </div>
   <div class="ai-gates wide">${aiGate(c2score>=num(c2.entry_threshold||70),`총점 ${num(c2.entry_threshold||70).toFixed(0)}↑`)}${aiGate(Boolean(k2.ready&&k2.up),'KOSPI 직전 완료 1분봉 상승')}${aiGate(Boolean(m2.ready&&m2.pass),'장기 고점일 종가 대비 60% 이하')}${aiGate(!g.event_block,'중대 악재 없음')}</div>
   <div class="ai-total-note">진입시간: 09:00~09:30 · 13:00~15:00 / 시간 외 예외진입 없음</div>
 </section>`;
 const c3score=num(c3.score||c1.score||0),entry=c3.entry_band||[2.7,3.3],target=c3.target_band||[4.7,5.3];
 const c3html=`<section class="ai-condition-card">
   <div class="ai-condition-head"><div><small>CONDITION 3</small><h3>조건3</h3></div><strong>${c3score.toFixed(1)}점</strong></div>
   <div class="ai-c3-grid">
     <div><span>전종목 감시</span><b>09:00~11:00</b><small>KOSPI·KOSDAQ 전체 스캔</small></div>
     <div><span>관찰 패턴</span><b>2.7~5.3%</b><small>관찰값 70% 이상 구간 유지 · 최소 15분</small></div>
     <div><span>진입 구간</span><b>${num(entry[0]).toFixed(1)}~${num(entry[1]).toFixed(1)}%</b><small>11:00~13:00 재진입 구간</small></div>
     <div><span>목표 구간</span><b>${num(target[0]).toFixed(1)}%↑</b><small>목표등락률 도달 시 청산</small></div>
   </div>
   <div class="ai-gates wide">${aiGate(Boolean(c3.sector_top3),'주도섹터 TOP3')}${aiGate(c3score>=num(c3.entry_threshold||75),`AI 점수 ${num(c3.entry_threshold||75).toFixed(0)}↑`)}${aiGate(num(c3.change_pct)>=num(entry[0])&&num(c3.change_pct)<=num(entry[1]),'현재 진입밴드')}</div>
   <div class="ai-total-note">전종목 스캔 90% 이상 완료 후 패턴 확정 · 13:00 전략 종료</div>
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
    print("NAMUH AI SCOREBOARD active: C1 entry->confirm->bonus + detailed C2/C3", flush=True)
    return True
