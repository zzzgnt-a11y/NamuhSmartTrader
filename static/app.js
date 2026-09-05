let STATE=null,refreshing=false,MODE=localStorage.getItem("GY_MARKET")||"KR";
let budgetInitialized=false,profitCursor=new Date(),profitMap={},selectedDate=null;
const $=id=>document.getElementById(id);
const won=n=>Number(n||0).toLocaleString("ko-KR")+"원";
const usd=n=>"$"+Number(n||0).toLocaleString("en-US",{minimumFractionDigits:2,maximumFractionDigits:4});
const pct=n=>(Number(n||0)>=0?"+":"")+Number(n||0).toFixed(2)+"%";
const price=(n,m=MODE)=>m==="US"?usd(n):won(n);
const esc=s=>String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;"}[c]));
const cache=new Map();
function html(id,value){if(cache.get(id)!==value){cache.set(id,value);const e=$(id);if(e)e.innerHTML=value}}
function text(id,value){const e=$(id);if(e&&e.textContent!==String(value))e.textContent=String(value)}
function spark(series){const v=(series||[]).map(Number).filter(Number.isFinite);if(v.length<2)return '<div class="source-note">추이 축적 중</div>';
  const w=180,h=38,min=Math.min(...v),max=Math.max(...v),span=max-min||1;
  const pts=v.map((x,i)=>`${i/(v.length-1)*w},${h-3-(x-min)/span*(h-6)}`).join(" ");
  return `<svg class="spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none"><line x1="0" y1="${h-3}" x2="${w}" y2="${h-3}"></line><polyline points="${pts}"></polyline></svg>`}
function applyMode(){
  document.body.dataset.market=MODE;localStorage.setItem("GY_MARKET",MODE);
  $("marketModeBtn")?.classList.toggle("us",MODE==="US");
  $("krModeLabel")?.classList.toggle("active",MODE==="KR");$("usModeLabel")?.classList.toggle("active",MODE==="US");
  const us=MODE==="US";
  text("subtitle",us?"NHPLUG 공식 데이터 기반 미장 기술적 단타 모의투자":"NHPLUG 공식 데이터 기반 국장 수급·기술 복합 모의투자");
  text("engineLabel",us?"US · TECHNICAL · PAPER":"KR · FLOW · PAPER");
  text("marketModeCaption",us?"미장 주요 지수 · 공식 데이터":"국장 주요 지수 · 공식 데이터");
  text("sectorCaption",us?"업종 움직임 참고":"수급·거래량·상승폭 복합 강도");
  text("scalpTitle",us?"미장 기술적 단타 탐지":"국장 단타 탐지");
  text("scalpCaption",us?"RSI · MACD · 볼린저 · 이평 · 거래량 · 가격구조":"체결강도 · 수급 · 섹터 · 기술 · 공시");
  $("smartSec")?.classList.toggle("hide",us);$("smartNavBtn")?.classList.toggle("hide",us);
}
async function setMode(m){MODE=m==="US"?"US":"KR";budgetInitialized=false;applyMode();await refresh(true)}
async function saveBudget(){
  const raw=String($("budget")?.value||"").replace(/,/g,"").trim(),amount=raw===""?null:Number(raw.replace(/\D/g,""));
  if(amount!==null&&(!Number.isFinite(amount)||amount<0||amount>1000000)){alert("0~1,000,000원 범위로 입력하거나 비워주세요.");return}
  const r=await fetch("/api/budget",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({amount,auto_max_if_unset:Boolean($("autoMaxIfUnset")?.checked)})});
  if(!r.ok){alert("운용금액 저장 실패");return}budgetInitialized=false;await refresh(true)
}
function markets(items){return (items||[]).map(x=>{const r=x.change_pct==null?null:Number(x.change_pct),cls=r==null?"":r>=0?"pos":"neg";
  return `<div class="market-card"><span>${esc(x.label)}</span><strong>${x.value==null?"—":Number(x.value).toLocaleString(undefined,{maximumFractionDigits:4})}</strong>
  <div class="delta ${cls}">${r==null?"":pct(r)}</div>${spark(x.series)}<div class="source-note">${esc((x.source||"")+" · "+(x.status||""))}</div></div>`}).join("")}
function sectors(items){return (items||[]).map((x,i)=>`<div class="sector-card"><span class="rank">${i+1}위 · SCORE ${Number(x.score||0).toFixed(1)}</span><b>${esc(x.sector)}</b>
  <div class="sector-meta"><span>등락 ${pct(x.change_pct)}</span><span>거래량 ${Number(x.volume_ratio||0).toFixed(0)}%</span>
  <span>상승비율 ${Number(x.breadth||0).toFixed(0)}%</span><span>${esc(x.leader||"-")}</span></div>
  <div class="strength-bar"><i style="width:${Math.min(100,Number(x.score||0)*10)}%"></i></div></div>`).join("")}
function candidateCard(x,smart=false,rank=0){
  const us=(x.market||MODE)==="US",ev=x.event;
  const metrics=smart?[
    ["현재가",price(x.price,x.market)],["외국인",Math.round(x.foreign_net||0).toLocaleString()],["기관",Math.round(x.institution_net||0).toLocaleString()],
    ["프로그램",Math.round(x.program_net||0).toLocaleString()],["10일 종가",x.smart_close_rank?`하위 ${x.smart_close_rank}위`:"대기"]
  ]:us?[
    ["현재가",price(x.price,"US")],["거래량",x.volume_ratio==null?"대기":Number(x.volume_ratio).toFixed(0)+"%"],["세션",x.phase||"-"],["통화","USD"],["상태",(x.reasons||[])[0]||"분석중"]
  ]:[
    ["현재가",price(x.price,"KR")],["체결강도",Number(x.execution_strength||0).toFixed(1)],["외국인",Math.round(x.foreign_net||0).toLocaleString()],
    ["기관",Math.round(x.institution_net||0).toLocaleString()],["프로그램",Math.round(x.program_net||0).toLocaleString()]
  ];
  return `<article class="candidate" data-stock="${esc(x.market)}/${esc(x.code)}"><div class="candidate-top"><div class="candidate-name"><b>${rank}. ${esc(x.name||x.code)}</b><small>${esc(x.code)} · ${esc(x.sector||"")}</small></div>
  <div class="score-badge">${Number(x.score||0).toFixed(0)}</div></div><div class="reason-row">${(x.reasons||[]).slice(0,5).map(r=>`<span class="pill">${esc(r)}</span>`).join("")}</div>
  <div class="metrics">${metrics.map(m=>`<div class="metric"><span>${esc(m[0])}</span><b>${esc(m[1])}</b></div>`).join("")}</div>
  ${smart?`<div class="smart-condition">${esc(x.smart_eligibility_reason||"10일 종가 조건 확인 중")}</div>`:""}
  ${ev?`<div class="event-tag ${ev.sentiment==="negative"?"negative":""}">${esc(ev.label)} · ${esc(ev.title)}</div>`:""}</article>`}
function eventRail(data){text("eventStatus",data?.status||"수신 대기");const items=data?.items||[];
  html("eventList",items.length?items.map(e=>`<div class="event-item"><div class="event-head"><span class="event-label ${e.sentiment==="negative"?"negative":""}">${esc(e.label)}</span><small>${esc(e.date)}</small></div>
  <b>${esc(e.corp_name||e.code)} · ${esc(e.title)}</b><small>AI 이벤트 ${Number(e.score||0).toFixed(1)}점 · ${esc(e.source||"")}</small><br><a href="${esc(e.url)}" target="_blank" rel="noopener">공시 원문 보기 ↗</a></div>`).join(""):'<div class="empty">최근 2일 공식 공시 없음 또는 DART 연결 대기</div>')}
function positionRow(p){return `<div class="position-row" data-stock="${esc(p.market)}/${esc(p.code)}"><div><b>${esc(p.name||p.code)}</b> <span class="strategy-tag">${esc(p.strategy||"SCALP")}</span><br><small>${esc(p.code)} · ${p.qty}주 · ${esc(p.entry_session||"")}</small></div>
  <div class="position-right"><b class="${p.pnl>=0?"pos":"neg"}">${pct(p.pnl_pct)}</b><br><small>${won(p.pnl)} · ${price(p.current_price,p.market)}</small></div></div>`}
function dateKey(d){return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,"0")}-${String(d.getDate()).padStart(2,"0")}`}
function buildProfit(trades){const m={};for(const t of trades||[]){if(t.side!=="SELL")continue;const k=t.date||dateKey(new Date());if(!m[k])m[k]={total:0,items:[]};m[k].total+=Number(t.pnl||0);m[k].items.push(t)}return m}
function drawCalendar(){const y=profitCursor.getFullYear(),m=profitCursor.getMonth(),first=new Date(y,m,1),last=new Date(y,m+1,0);text("profitMonthTitle",`${y}년 ${m+1}월`);
  const cells=[];for(let i=0;i<first.getDay();i++)cells.push(null);for(let d=1;d<=last.getDate();d++)cells.push(new Date(y,m,d));
  html("profitCalendar",cells.map(d=>{if(!d)return '<div></div>';const k=dateKey(d),v=profitMap[k]?.total;
    return `<button class="day-cell ${selectedDate===k?"active":""}" data-date="${k}"><div class="d">${d.getDate()}</div><div class="p ${Number(v||0)>=0?"pos":"neg"}">${v==null?"":won(v)}</div></button>`}).join(""))}
function showProfit(k){selectedDate=k;const d=profitMap[k];text("profitSummary",`${k} 실현손익 · ${won(d?.total||0)}`);
  html("profitDetailList",d?d.items.map(t=>`<div class="profit-row"><div><b>${esc(t.name||t.code)}</b><br><small>${esc(t.time)} · ${esc(t.strategy||"")}</small></div><div><b class="${t.pnl>=0?"pos":"neg"}">${won(t.pnl)}</b><br><small>${pct(t.pnl_pct)}</small></div></div>`).join(""):'<div class="empty">매매내역 없음</div>');drawCalendar()}
function render(s){
  if(!s||s.mode!==MODE)throw new Error("market state mismatch");STATE=s;const p=s.paper||{},sc=s.schedule||{},h=s.health||{};
  text("equity",won(p.equity));text("heroBudget",won(p.effective_budget));text("heroSession",sc.kr_scalp_session||sc.label||"-");
  text("health",h.nh_configured?`NH · KR ${h.kr_priced||0}/${h.kr_tracked||0} · US ${h.us_priced||0}/${h.us_tracked||0}`:"NH API 키 미설정");
  text("heldCost",`보유원가 ${won(p.held_cost)} / 한도 ${won(p.effective_budget)}`);
  if(!budgetInitialized){$("budget").value=p.explicit_budget==null?"":p.explicit_budget;$("autoMaxIfUnset").checked=Boolean(p.auto_max_if_unset);budgetInitialized=true}
  text("currentBudget",p.explicit_budget==null?(p.auto_max_if_unset?`현재 운용값: 자동 최대 ${won(p.effective_budget)}`:"현재 운용값: 미설정(매수 중지)"):`현재 운용값: ${won(p.effective_budget)}`);
  text("fxNote",p.usdkrw>0?`USD/KRW ${Number(p.usdkrw).toLocaleString()}원 · ${p.usdkrw_asof||"공식값"}`:"USD/KRW 공식 환율 수신 대기 · 미장 신규매수 차단");
  text("scheduleCard",`${sc.kr_scalp_rules||""} · 미장 ${sc.us_hours||""} · 현재 ${sc.label||"-"}`);
  text("updatedClock",new Date().toLocaleTimeString("ko-KR",{hour12:false})+" 업데이트");
  if(MODE==="KR"&&s.session){text("sessionStatus",`${s.session.label} · ${s.session.status}`);$("sessionStatus").hidden=false}else $("sessionStatus").hidden=true;
  html("markets",markets(s.market));html("sectors",sectors(s.sectors));
  const scalp=s.scalp||[],smart=s.smart||[];text("topScalp",scalp[0]?`${scalp[0].name} ${Number(scalp[0].score).toFixed(0)}점`:"분석 중");
  text("topSector",s.sectors?.[0]?.sector||"분석 중");
  html("scalpList",scalp.length?scalp.map((x,i)=>candidateCard(x,false,i+1)).join(""):'<div class="empty">후보 데이터 축적 중</div>');
  if(MODE==="KR")html("smartList",smart.length?smart.map((x,i)=>candidateCard(x,true,i+1)).join(""):'<div class="empty">스마트머니 후보 축적 중</div>');
  html("positions",(p.positions||[]).length?p.positions.map(positionRow).join(""):'<div class="empty">현재 보유종목이 없습니다.</div>');
  eventRail(s.events);profitMap=buildProfit(p.trades||[]);drawCalendar();
  if(s.market_separation&&!s.market_separation.ok)throw new Error("market separation violation")
}
async function refresh(force=false){if(refreshing&&!force)return;refreshing=true;try{const r=await fetch(`/api/state?market=${MODE}`,{cache:"no-store"});if(!r.ok)throw new Error(`state ${r.status}`);render(await r.json())}catch(e){console.error(e);text("health","서버/데이터 연결 오류")}finally{refreshing=false}}
function bind(){
  $("saveBudgetBtn")?.addEventListener("click",saveBudget);$("marketModeBtn")?.addEventListener("click",()=>setMode(MODE==="KR"?"US":"KR"));
  $("krModeLabel")?.addEventListener("click",()=>setMode("KR"));$("usModeLabel")?.addEventListener("click",()=>setMode("US"));
  document.querySelectorAll("[data-scroll]").forEach(b=>b.addEventListener("click",()=>{$(b.dataset.scroll)?.scrollIntoView({behavior:"smooth",block:"start"});document.querySelectorAll(".side-btn").forEach(x=>x.classList.remove("active"));b.classList.add("active")}));
  document.addEventListener("click",e=>{const s=e.target.closest?.("[data-stock]");if(s){location.href="/stock/"+s.dataset.stock;return}const d=e.target.closest?.("[data-date]");if(d)showProfit(d.dataset.date)});
  $("prevMonthBtn")?.addEventListener("click",()=>{profitCursor=new Date(profitCursor.getFullYear(),profitCursor.getMonth()-1,1);drawCalendar()});
  $("nextMonthBtn")?.addEventListener("click",()=>{profitCursor=new Date(profitCursor.getFullYear(),profitCursor.getMonth()+1,1);drawCalendar()});
}
document.addEventListener("DOMContentLoaded",()=>{applyMode();bind();refresh();setInterval(refresh,5000)});
