(()=>{
'use strict';
const $=s=>document.querySelector(s),esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[c]));
const won=n=>Math.round(Number(n||0)).toLocaleString('ko-KR')+'원';
const pct=n=>(Number(n||0)>=0?'+':'')+Number(n||0).toFixed(2)+'%';
const qty=n=>Math.max(0,Number(n||0)).toLocaleString('ko-KR',{maximumFractionDigits:8})+'주';
let lastState=null,lastTradeKey='',queued=false;
function market(){return $('#usModeLabel')?.classList.contains('active')?'US':'KR'}
function unitPrice(n,m){return m==='US'?'$'+Number(n||0).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:4}):Math.round(Number(n||0)).toLocaleString('ko-KR')+'원'}
function stableLabels(){
 const m=market(),title=$('#scalpTitle'),sub=$('#subtitle');
 if(title){const want=m==='US'?'미장 단타 탐지':'국장 단타 탐지';if(title.textContent!==want)title.textContent=want}
 if(sub&&sub.textContent!=='with Alice')sub.textContent='with Alice';
}
function removeTradeFilters(){document.querySelectorAll('[data-trade-filter],.trade-filter,.trade-filter-buttons,.trade-side-filter').forEach(x=>x.remove())}
function ensureTradeSection(){
 let sec=$('#tradeSec');
 if(!sec){
  const profit=$('#profitSec');if(!profit)return null;
  sec=document.createElement('section');sec.id='tradeSec';sec.className='section-shell';
  sec.innerHTML='<div class="section-head"><div><span class="section-index">05</span><div><small>TRADE HISTORY</small><h2>거래내역</h2></div></div><b id="v361TradeScope"></b></div><div id="stockTrades" class="stock-trade-list"></div>';
  profit.parentNode.insertBefore(sec,profit);const pi=profit.querySelector('.section-index');if(pi)pi.textContent='06';
 }
 let scope=sec.querySelector('#v361TradeScope');if(!scope){scope=sec.querySelector('.section-head>b');if(scope)scope.id='v361TradeScope'}
 removeTradeFilters();return sec;
}
function strategy(t){const s=String(t?.strategy_display||t?.strategy||'').trim();return s==='SCALP'?'조건1':s}
function renderTrades(state){
 const d=state||lastState;if(!d)return;lastState=d;const m=String(d.mode||market()).toUpperCase(),trades=Array.isArray(d?.paper?.trades)?d.paper.trades:[];
 const sec=ensureTradeSection(),box=$('#stockTrades');if(!sec||!box)return;const scope=$('#v361TradeScope');if(scope)scope.textContent=m==='US'?'미장 모의매매 내역':'국장 모의매매 내역';
 const rows=trades.slice(0,80),key=m+'|'+rows.map(t=>[t.side,t.code,t.qty,t.price,t.date,t.time,t.strategy_display||t.strategy,t.reason,t.pnl,t.pnl_pct].join(':')).join('|');if(key===lastTradeKey&&box.dataset.v361==='1')return;lastTradeKey=key;box.dataset.v361='1';
 box.innerHTML=rows.length?rows.map(t=>{const side=String(t.side||'').toUpperCase(),st=strategy(t),reason=String(t.reason||'').trim(),detail=[st,reason&&reason!==st?reason:''].filter(Boolean).join(' · '),p=Number(t.pnl||0),pp=Number(t.pnl_pct||0),unit=side==='BUY'?'매수가':'매도가',amount=side==='SELL'?`${won(p)} · ${pct(pp)}`:`매수금액 ${won(t.gross_krw)}`;return `<div class="stock-trade-row"><div><span class="trade-side ${side==='BUY'?'buy':'sell'}">${esc(side)}</span><b>${esc(t.name||t.code)}</b><small>${esc(t.date||'')} ${esc(t.time||'')}${detail?' · '+esc(detail):''}</small></div><div><b>${unit} ${unitPrice(t.price,m)} · ${qty(t.qty)}</b><small class="${p>=0?'pos':'neg'}">${amount}</small></div></div>`}).join(''):`<div class="empty">아직 ${m==='US'?'미장':'국장'} 모의매매 내역이 없습니다.</div>`;
}
function linkUsSectors(){if(market()!=='US')return;document.querySelectorAll('#sectors .sector-card').forEach(card=>{const name=card.querySelector('b')?.textContent?.trim();if(name&&!card.dataset.sector){card.dataset.sector=name;card.setAttribute('role','button');card.tabIndex=0;card.style.cursor='pointer'}})}
function conditionMatched(x){
 const labels=[];const c1=x?.condition1||{},c2=x?.condition2||{},c3=x?.condition3||{};
 if(c1.gate===true)labels.push({name:'조건1',score:Number(c1.score??x.score??0)});
 if(c2.gate===true||x?.condition2_gate_pass===true)labels.push({name:'조건2',score:Number(c2.score??x.condition2_score??0)});
 if(c3.gate===true||(Array.isArray(x?.condition_labels)&&x.condition_labels.includes('조건3')))labels.push({name:'조건3',score:Number(c3.score??x.score??0)});
 return labels;
}
function renderConditions(){
 stableLabels();const map=window.NAMUH_ALL_SCORE_MAP;document.querySelectorAll('#scalpList .v352-ai-card').forEach(card=>{const code=String(card.dataset.stock||'').split('/').pop().toUpperCase(),x=map?.get(code);if(!x)return;const box=card.querySelector('.metrics'),reason=card.querySelector('.reason-row');if(reason)reason.style.display='none';if(!box)return;const matched=conditionMatched(x);let next;if(matched.length>=2){next='<span class="v361-condition on">복합조건</span>'}else if(matched.length===1){const a=matched[0];next=`<span class="v361-condition on">${esc(a.name)} ${Number(a.score||0).toFixed(0)}점</span>`}else{next='<span class="v361-condition wait">조건 대기</span>'}box.classList.add('strategy123-box');if(box.innerHTML!==next)box.innerHTML=next});
 document.querySelectorAll('#positions .strategy-tag').forEach(t=>{if(t.textContent.trim()==='SCALP')t.textContent='조건1'});
}
function renderForecast(f){
 const sec=$('#smartSec');if(!sec)return;let box=$('#v361SmartForecast');if(!box){box=document.createElement('div');box.id='v361SmartForecast';box.className='v361-smart-forecast';const list=$('#smartList');if(list)list.parentNode.insertBefore(box,list)}
 if(market()!=='KR'){box.style.display='none';return}box.style.display='';if(!f||!f.ready){box.innerHTML=`<small>KOSPI 5년 분석</small><b>분석 준비 중</b><span>${esc(f?.reason||'5년 공식 일봉 수집 중')}</span>`;return}
 const prob=Number(f.up_probability_pct||0),ret=Number(f.expected_return_pct||0),idx=Number(f.expected_index||0);box.innerHTML=`<small>KOSPI 5년 유사국면 · ${esc(f.horizon||'5거래일')}</small><b>상승가능성 ${prob.toFixed(1)}%</b><span>예상 지수 ${idx.toLocaleString(undefined,{maximumFractionDigits:2})} · ${ret>=0?'+':''}${ret.toFixed(2)}%</span><em>${esc(f.basis||'')}</em>`;
}
function refreshCalendarDetail(){setTimeout(()=>{const active=$('#profitCalendar .day-cell.active')||[...document.querySelectorAll('#profitCalendar .day-cell')].find(x=>x.classList.contains('today'));active?.click()},80)}
function onState(d){if(!d||!d.mode)return;lastState=d;setTimeout(()=>{stableLabels();renderTrades(d);renderForecast(d.smart_money_forecast);linkUsSectors();renderConditions();refreshCalendarDetail();removeTradeFilters()},20)}
function schedule(){if(queued)return;queued=true;requestAnimationFrame(()=>{queued=false;stableLabels();linkUsSectors();renderConditions();removeTradeFilters()})}
function style(){if($('#v361Style'))return;const s=document.createElement('style');s.id='v361Style';s.textContent=`
.v361-condition{display:inline-flex;align-items:center;border-radius:999px;padding:7px 11px;font-size:12px;font-weight:900;border:1px solid rgba(80,105,160,.18)}.v361-condition.on{background:rgba(35,145,95,.10);border-color:rgba(35,145,95,.28)}.v361-condition.wait{opacity:.62;background:rgba(90,105,145,.05)}
.v361-smart-forecast{margin:0 0 10px;padding:11px 12px;border:1px solid rgba(71,105,189,.16);border-radius:14px;background:rgba(71,105,189,.05);display:grid;gap:3px}.v361-smart-forecast small{font-size:9px;color:#72819b}.v361-smart-forecast b{font-size:14px}.v361-smart-forecast span{font-size:12px;font-weight:800}.v361-smart-forecast em{font-style:normal;font-size:9px;color:#7f8ba0}
#sectors .sector-card[data-sector]{transition:transform .12s ease,border-color .12s ease}#sectors .sector-card[data-sector]:active{transform:scale(.99)}
`;document.head.appendChild(s)}
function init(){
 style();stableLabels();ensureTradeSection();removeTradeFilters();linkUsSectors();renderConditions();
 const scalp=$('#scalpList');if(scalp)new MutationObserver(schedule).observe(scalp,{childList:true,subtree:false});const sectors=$('#sectors');if(sectors)new MutationObserver(schedule).observe(sectors,{childList:true,subtree:false});
 ['#krModeLabel','#usModeLabel'].forEach(sel=>$(sel)?.addEventListener('click',()=>{const pd=$('#profitDetailList'),ps=$('#profitSummary');if(pd)pd.innerHTML='<div class="empty">시장 전환 중</div>';if(ps)ps.textContent='시장 전환 중';setTimeout(schedule,30)}));
 document.addEventListener('keydown',e=>{const card=e.target.closest?.('#sectors .sector-card[data-sector]');if(card&&(e.key==='Enter'||e.key===' ')){e.preventDefault();card.click()}});
}
if(!window.__NAMUH_V361_STATE_FETCH__){window.__NAMUH_V361_STATE_FETCH__=true;const nativeFetch=window.fetch.bind(window);window.fetch=async(...args)=>{const res=await nativeFetch(...args);try{const u=String(args?.[0] instanceof Request?args[0].url:args?.[0]||'');if(u.includes('/api/state'))res.clone().json().then(onState).catch(()=>{})}catch(_){}return res}}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});else init();
})();
