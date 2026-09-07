(()=>{
'use strict';
const $=s=>document.querySelector(s);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot',"'":'&#039;'}[c]));
const ui={scores:{KR:[],US:[]},tradeFilter:{KR:'ALL',US:'ALL'}};
let lastMarket='';
function market(){return $('#usModeLabel')?.classList.contains('active')?'US':'KR'}
function kst(){return new Date(Date.now()+9*3600000)}
function ymd(d=kst()){return `${d.getUTCFullYear()}-${String(d.getUTCMonth()+1).padStart(2,'0')}-${String(d.getUTCDate()).padStart(2,'0')}`}
function hm(d=kst()){return `${String(d.getUTCHours()).padStart(2,'0')}:${String(d.getUTCMinutes()).padStart(2,'0')}`}
function n(v){const x=Number(String(v??0).replace(/,/g,''));return Number.isFinite(x)?x:0}
function won(v){return `${Math.round(n(v)).toLocaleString('ko-KR')}원`}
function signed(v){const x=n(v),a=Math.abs(x);let s;if(a>=1e12)s=(a/1e12).toFixed(1)+'조';else if(a>=1e8)s=(a/1e8).toFixed(0)+'억';else if(a>=1e4)s=(a/1e4).toFixed(0)+'만';else s=Math.round(a).toLocaleString('ko-KR');return `${x>0?'+':x<0?'-':''}${s}`}
function side(t){return String(t?.side||'').toUpperCase()}
function tradeMarket(t){const m=String(t?.market||t?.market_type||'').toUpperCase();if(m==='KR'||m==='US')return m;return /^[A-Z]/.test(String(t?.code||''))?'US':'KR'}
function conditionLabel(x){
  const exact=String(x?.condition_display||'').trim();
  if(exact==='복합조건'||/^조건[123]$/.test(exact))return exact;
  const a=[];
  for(const raw of (Array.isArray(x?.condition_labels)?x.condition_labels:[])){const s=String(raw||'').trim();if(/^조건[123]$/.test(s)&&!a.includes(s))a.push(s)}
  if(!a.length){if(x?.condition1?.gate)a.push('조건1');if(x?.condition2?.gate||x?.condition2_gate_pass)a.push('조건2');if(x?.condition3?.gate)a.push('조건3')}
  return a.length>1?'복합조건':a[0]||'';
}
function installStyle(){
  if($('#v363Style'))return;
  const s=document.createElement('style');s.id='v363Style';s.textContent=`
  .v363-info-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin:14px 0 18px}.v363-panel{border:1px solid rgba(80,100,140,.14);border-radius:14px;padding:12px;background:rgba(255,255,255,.55)}.v363-panel-head{display:flex;justify-content:space-between;gap:10px;align-items:center;margin-bottom:10px}.v363-panel-head b{font-size:13px}.v363-panel-head span{font-size:10px;opacity:.65}.v363-time-scores{display:flex;gap:7px;overflow:auto;padding-bottom:3px}.v363-time-card{min-width:116px;border:1px solid rgba(80,100,140,.12);border-radius:10px;padding:8px;display:grid;gap:2px}.v363-time-card>b{font-size:10px;opacity:.65}.v363-time-card>strong{font-size:20px}.v363-time-card>span{font-size:11px;font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.v363-time-card>small{font-size:9px;opacity:.65}.v363-flow-rows{display:grid;gap:7px}.v363-flow-row{display:grid;grid-template-columns:70px repeat(3,1fr);gap:8px;align-items:center;font-size:11px;border-bottom:1px solid rgba(80,100,140,.09);padding:6px 0}.v363-flow-row:last-child{border-bottom:0}.v363-flow-row em{font-style:normal;font-weight:800}.v363-muted{opacity:.68}.v363-condition{font-weight:800}.v363-filter{display:flex;gap:6px}.v363-filter button{border:1px solid rgba(80,100,140,.18);border-radius:999px;padding:7px 11px;background:transparent;font-weight:700}.v363-filter button.active{background:rgba(70,100,160,.12);border-color:rgba(70,100,160,.35)}.v363-trades{display:grid;gap:7px}.v363-trade-row{display:flex;justify-content:space-between;gap:12px;align-items:center;padding:10px 4px;border-bottom:1px solid rgba(80,100,140,.1)}.v363-trade-row>div{display:grid;grid-template-columns:auto auto;gap:3px 7px;align-items:center}.v363-trade-row small{grid-column:1/-1;font-size:10px;opacity:.7}.v363-trade-row>div:last-child{text-align:right}.v363-empty{font-size:11px;opacity:.6;padding:8px}.trade-side{font-size:10px;font-weight:900;border-radius:999px;padding:3px 6px}.trade-side.buy{background:rgba(40,120,230,.1)}.trade-side.sell{background:rgba(220,70,70,.1)}
  @media(max-width:800px){.v363-info-grid{grid-template-columns:1fr}.v363-flow-row{grid-template-columns:62px 1fr 1fr 1fr;font-size:10px}.v363-trade-row{align-items:flex-start}}
  `;document.head.appendChild(s);
}
function ensurePanels(){
  installStyle();
  const scalp=$('#scalpSec');
  if(scalp&&!$('#v363InfoGrid')){
    const grid=document.createElement('div');grid.id='v363InfoGrid';grid.className='v363-info-grid';
    grid.innerHTML=`<section class="v363-panel"><div class="v363-panel-head"><b>시간대별 AI 점수</b><span id="v363AiMeta">수신 대기</span></div><div id="v363TimeScores" class="v363-time-scores"><div class="v363-empty">AI 점수 축적 중</div></div></section><section id="v363KrFlowPanel" class="v363-panel"><div class="v363-panel-head"><b>KOSPI · KOSDAQ 금일 수급</b><span id="v363FlowMeta">KRX 수신 대기</span></div><div id="v363FlowRows" class="v363-flow-rows"><div class="v363-empty">국장에서 표시됩니다.</div></div></section>`;
    scalp.querySelector('.section-head')?.after(grid);
  }
  ensureTradeSection();
}
function bucket(){const d=kst(),m=Math.floor(d.getUTCMinutes()/10)*10;return `${String(d.getUTCHours()).padStart(2,'0')}:${String(m).padStart(2,'0')}`}
function historyKey(m){return `GY_AI_TIME_V363_${m}_${ymd()}`}
function readHistory(m){try{const a=JSON.parse(localStorage.getItem(historyKey(m))||'[]');return Array.isArray(a)?a:[]}catch(_){return []}}
function saveSnapshot(m,rows){
  if(!rows.length)return;
  const sorted=rows.slice().sort((a,b)=>n(b.score)-n(a.score)),top10=sorted.slice(0,10);
  const snap={time:bucket(),top:n(sorted[0]?.score),topName:String(sorted[0]?.name||sorted[0]?.code||''),avg:top10.length?top10.reduce((s,x)=>s+n(x.score),0)/top10.length:0,ready:sorted.filter(x=>n(x.score)>=72).length,count:sorted.length,ts:Date.now()};
  let h=readHistory(m).filter(x=>x&&x.time!==snap.time);h.push(snap);h=h.slice(-30);try{localStorage.setItem(historyKey(m),JSON.stringify(h))}catch(_){}
}
function renderTimeScores(){
  const m=market(),box=$('#v363TimeScores'),meta=$('#v363AiMeta');if(!box)return;
  const h=readHistory(m),live=ui.scores[m]||[];if(meta)meta.textContent=`${m} · 10분 고정 · ${live.length}종목`;
  if(!h.length){box.innerHTML='<div class="v363-empty">AI 점수 축적 중</div>';return}
  box.innerHTML=h.slice(-12).map(x=>`<div class="v363-time-card"><b>${esc(x.time)}</b><strong>${Math.round(n(x.top))}점</strong><span>${esc(x.topName||'TOP')}</span><small>TOP10 평균 ${Math.round(n(x.avg))} · 72↑ ${n(x.ready)}종</small></div>`).join('');
}
async function loadUniverse(){
  if(document.hidden)return;const m=market();
  try{const r=await fetch(`/api/v352/universe?market=${m}&catalog=0`,{cache:'no-store'});if(!r.ok)throw new Error(String(r.status));const d=await r.json();const rows=Array.isArray(d.scores)?d.scores:[];ui.scores[m]=rows;saveSnapshot(m,rows);renderTimeScores();annotateConditions(rows,m)}catch(_){const meta=$('#v363AiMeta');if(meta)meta.textContent=`${m} · AI 수신 재시도`}
}
function cardCode(card,m){let raw=String(card.dataset.stock||card.dataset.code||'');let code=raw.split('/').pop()||'';if(code)return code.toUpperCase();const text=card.querySelector('.candidate-name small')?.textContent||'';const mm=text.match(m==='KR'?/\b\d{6}\b/:/\b[A-Z][A-Z0-9.\-]{0,9}\b/);return (mm?.[0]||'').toUpperCase()}
function annotateConditions(rows,m){
  const map=new Map(rows.map(x=>[String(x.code||'').toUpperCase(),x]));
  document.querySelectorAll('#scalpList .candidate').forEach(card=>{const x=map.get(cardCode(card,m));if(!x)return;let chip=card.querySelector('.v363-condition');if(!chip){chip=document.createElement('span');chip.className='v363-condition';card.querySelector('.candidate-name small')?.append(chip)}const label=conditionLabel(x);chip.textContent=label?` · ${label}`:''});
  document.querySelectorAll('#positions .strategy-tag').forEach(t=>{if(t.textContent.trim()==='SCALP')t.textContent='조건1'});
}
async function loadFlows(){
  const panel=$('#v363KrFlowPanel');if(!panel)return;
  if(market()!=='KR'){panel.classList.add('v363-muted');$('#v363FlowRows').innerHTML='<div class="v363-empty">국장(KR)에서 KOSPI·KOSDAQ 금일 수급을 표시합니다.</div>';$('#v363FlowMeta').textContent='KR 전용';return}
  panel.classList.remove('v363-muted');if(document.hidden)return;
  try{const r=await fetch('/api/v363/kr-market-flow',{cache:'no-store'});const d=await r.json();if(!r.ok||!d.ok)throw new Error(d.error||r.status);const rows=d.markets||{};$('#v363FlowRows').innerHTML=['KOSPI','KOSDAQ'].map(k=>{const x=rows[k]||{};return `<div class="v363-flow-row"><b>${k}</b><span>외국인 <em class="${n(x.foreign)>=0?'pos':'neg'}">${signed(x.foreign)}</em></span><span>기관 <em class="${n(x.institution)>=0?'pos':'neg'}">${signed(x.institution)}</em></span><span>개인 <em class="${n(x.person)>=0?'pos':'neg'}">${signed(x.person)}</em></span></div>`}).join('');$('#v363FlowMeta').textContent=`${d.asof||ymd()} · ${d.source||'KRX'} · ${d.updated_hm||hm()}`}
  catch(_){$('#v363FlowRows').innerHTML='<div class="v363-empty">KRX 공식 수급 재조회 중</div>';$('#v363FlowMeta').textContent='공식데이터 재시도'}
}
function ensureTradeSection(){
  if($('#v363TradeSec'))return;const profit=$('#profitSec');if(!profit)return;
  const sec=document.createElement('section');sec.id='v363TradeSec';sec.className='section-shell v363-trade-section';sec.innerHTML=`<div class="section-head"><div><span class="section-index">07</span><div><small>STOCK TRADE HISTORY</small><h2 id="v363TradeTitle">국장 거래내역</h2></div></div><div class="v363-filter" id="v363TradeFilter"><button data-filter="ALL" class="active">전체</button><button data-filter="BUY">매수</button><button data-filter="SELL">매도</button></div></div><div id="v363Trades" class="v363-trades"><div class="v363-empty">거래내역 없음</div></div>`;profit.before(sec);
  sec.querySelectorAll('[data-filter]').forEach(b=>b.addEventListener('click',()=>{ui.tradeFilter[market()]=b.dataset.filter||'ALL';renderTrades(typeof STATE!=='undefined'?STATE:{});syncFilterButtons()}));
}
function syncFilterButtons(){const f=ui.tradeFilter[market()]||'ALL';$('#v363TradeFilter')?.querySelectorAll('button').forEach(b=>b.classList.toggle('active',b.dataset.filter===f))}
function stockTrades(trades,m){const f=ui.tradeFilter[m]||'ALL';return (trades||[]).filter(t=>tradeMarket(t)===m&&(f==='ALL'||side(t)===f))}
function tradeRow(t){const s=side(t),sell=s==='SELL';return `<div class="v363-trade-row"><div><span class="trade-side ${s==='BUY'?'buy':'sell'}">${esc(s||'-')}</span><b>${esc(t.name||t.code||'-')}</b><small>${esc(t.date||'')} ${esc(t.time||'')} · ${esc(t.reason||t.strategy||'')}</small></div><div><b>${n(t.price).toLocaleString(undefined,{maximumFractionDigits:4})}</b><small class="${n(t.pnl)>=0?'pos':'neg'}">${sell?won(t.pnl):won(t.gross_krw||0)}</small></div></div>`}
function renderTrades(s){ensureTradeSection();const m=market(),p=s?.paper||s?.account||{},rows=stockTrades(p.trades||[],m).slice().reverse().slice(0,100);const title=$('#v363TradeTitle');if(title)title.textContent=m==='US'?'미장 거래내역':'국장 거래내역';const box=$('#v363Trades');if(box)box.innerHTML=rows.map(tradeRow).join('')||'<div class="v363-empty">해당 필터 거래내역 없음</div>';syncFilterButtons()}
function installCalendarFix(){
  if(window.__V363_CALENDAR__)return;window.__V363_CALENDAR__=true;
  if(typeof window.buildProfit==='function')window.buildProfit=function(trades){const m=market(),map={};for(const t of (trades||[])){if(side(t)!=='SELL'||tradeMarket(t)!==m)continue;const k=String(t.date||'').slice(0,10);if(!k)continue;if(!map[k])map[k]={total:0,items:[]};map[k].total+=n(t.pnl);map[k].items.push(t)}return map};
  if(typeof window.showDay==='function')window.showDay=function(k){
    try{selectedDate=k}catch(_){};document.querySelectorAll('.cal-day').forEach(x=>x.classList.toggle('selected',x.dataset.date===k));
    let d=null,ev=[];try{d=profitMap?.[k];ev=(events||[]).filter(e=>String(e.date||'').slice(0,10)===k)}catch(_){}
    const ps=$('#profitSummary');if(ps)ps.textContent=d?`${k} · 실현손익 ${won(d.total)} · 중요일정 ${ev.length}건`:`${k} · 실현 매매 없음 · 중요일정 ${ev.length}건`;
    const pb=$('#profitDetail');if(pb)pb.innerHTML=d?.items?.length?d.items.map(t=>`<div><span>${esc(t.time||'')} ${esc(t.name||t.code||'')} 매도</span><b class="${n(t.pnl)>=0?'pos':'neg'}">${won(t.pnl)}</b></div>`).join(''):'<div class="empty-line">실현 매매 없음</div>';
    const eb=$('#eventDetail');if(eb)eb.innerHTML=ev.length?ev.map(e=>`<div><span>${esc(e.time||'')} ${esc(e.name||e.code||'')}</span><b>${esc(e.title||'')}</b><small>${esc(e.sentiment||'중립')}</small></div>`).join(''):'<div class="empty-line">중요 일정 없음</div>';
  };
}
function hookOwners(){
  if(window.__V363_OWNER_HOOK__)return;window.__V363_OWNER_HOOK__=true;
  const oldRender=window.render;if(typeof oldRender==='function')window.render=function(s){const out=oldRender(s);renderTrades(s);queueMicrotask(()=>annotateConditions(ui.scores[market()]||[],market()));return out};
  const oldSet=window.setMode;if(typeof oldSet==='function')window.setMode=function(m){try{selectedDate=null}catch(_){}const out=oldSet(m);setTimeout(onMarketChange,120);return out};
}
function refreshCalendarForMarket(){try{const p=STATE?.paper||{};profitMap=buildProfit(p.trades||[]);drawCalendar();showDay(ymd())}catch(_){}}
function onMarketChange(){
  const m=market();if(m===lastMarket)return;lastMarket=m;ensurePanels();renderTimeScores();syncFilterButtons();loadUniverse();loadFlows();try{renderTrades(STATE||{})}catch(_){};refreshCalendarForMarket();
}
function init(){
  ensurePanels();installCalendarFix();hookOwners();onMarketChange();
  ['#krModeLabel','#usModeLabel'].forEach(sel=>$(sel)?.addEventListener('click',()=>setTimeout(onMarketChange,150)));
  document.addEventListener('visibilitychange',()=>{if(!document.hidden){loadUniverse();loadFlows()}});
  setInterval(loadUniverse,20000);setInterval(loadFlows,60000);
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});else init();
})();
