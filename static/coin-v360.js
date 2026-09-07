(()=>{
'use strict';
const $=s=>document.querySelector(s);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[c]));
let latest=[],filter='ALL',lastKey='';
const won=n=>'₩'+Math.round(Number(n||0)).toLocaleString('ko-KR');
const pct=n=>(Number(n||0)>=0?'+':'')+Number(n||0).toFixed(2)+'%';
function fmt(n){const v=Number(n||0);return v>=1000?won(v):v.toLocaleString(undefined,{maximumFractionDigits:8})+'원'}
function st(x){const s=String(x?.strategy_display||x?.strategy||'').trim();return s==='COIN_SCALP'||s==='SCALP'?'조건1':s}
function ensureStyle(){if($('#coinV360Style'))return;const s=document.createElement('style');s.id='coinV360Style';s.textContent=`
.v360-coin-filters{margin-left:auto;display:flex;gap:6px;align-items:center;justify-content:flex-end}
.v360-coin-filters button{border:1px solid rgba(119,35,72,.22);background:rgba(255,255,255,.55);border-radius:999px;padding:5px 9px;font-size:10px;font-weight:900}
.v360-coin-filters button.active{background:rgba(119,35,72,.13);border-color:rgba(119,35,72,.4)}
.v360-cond{display:inline-flex;margin-left:5px;padding:3px 6px;border-radius:999px;border:1px solid rgba(119,35,72,.18);font-size:9px;font-weight:900}
`;document.head.appendChild(s)}
function ensureFilters(){const head=$('#coinTradeSec .section-head');if(!head)return;let box=head.querySelector('.v360-coin-filters');if(box)return;const old=head.querySelector(':scope > b');if(old)old.remove();box=document.createElement('div');box.className='v360-coin-filters';box.innerHTML='<button data-cf="ALL" class="active">전체</button><button data-cf="BUY">매수</button><button data-cf="SELL">매도</button>';head.appendChild(box);box.addEventListener('click',e=>{const b=e.target.closest('[data-cf]');if(!b)return;filter=b.dataset.cf;box.querySelectorAll('button').forEach(x=>x.classList.toggle('active',x===b));renderTrades()})}
function renderTrades(){ensureFilters();const box=$('#coinTrades');if(!box)return;const rows=latest.filter(t=>filter==='ALL'||String(t.side||'').toUpperCase()===filter).slice(0,100);const key=filter+'|'+rows.map(t=>[t.side,t.code,t.price,t.qty,t.date,t.time,t.strategy_display,t.strategy,t.reason,t.pnl].join(':')).join('|');if(key===lastKey&&box.dataset.v360==='1')return;lastKey=key;box.dataset.v360='1';box.innerHTML=rows.length?rows.map(t=>{const side=String(t.side||'').toUpperCase(),label=st(t),reason=String(t.reason||'').trim(),detail=[label,reason&&reason!==label?reason:''].filter(Boolean).join(' · '),pnl=Number(t.pnl||0);return `<div class="coin-trade-row"><div><span class="trade-side ${side==='BUY'?'buy':'sell'}">${side==='BUY'?'매수':'매도'}</span><b>${esc(t.name||t.code)}</b><small>${esc(t.date||'')} ${esc(t.time||'')}${detail?' · '+esc(detail):''}</small></div><div><b>${fmt(t.price)} · ${Number(t.qty||0).toLocaleString(undefined,{maximumFractionDigits:8})}개</b><small class="${pnl>=0?'pos':'neg'}">${side==='SELL'?won(pnl)+' · '+pct(t.pnl_pct):won(t.gross_krw)}</small></div></div>`}).join(''):'<div class="empty">해당 거래내역이 없습니다.</div>'}
function annotateCandidates(rows){const cards=[...document.querySelectorAll('#coinCandidateList .coin-candidate')];cards.forEach((card,i)=>{card.querySelectorAll('.v360-cond').forEach(x=>x.remove());const x=rows?.[i];if(!x)return;const labels=Array.isArray(x.condition_labels)?x.condition_labels:[];const target=card.querySelector('.reason-row')||card.querySelector('.candidate-name');labels.forEach(l=>{const s=document.createElement('span');s.className='v360-cond';s.textContent=l;target?.appendChild(s)})})}
function annotatePositions(rows){const cards=[...document.querySelectorAll('#coinPositions .position-row')];cards.forEach((card,i)=>{const p=rows?.[i];if(!p)return;const tag=card.querySelector('.strategy-tag');if(tag)tag.textContent=st(p)||'조건1'})}
function apply(d){const a=d?.account||{};latest=Array.isArray(a.trades)?a.trades:[];setTimeout(()=>{renderTrades();annotateCandidates(d?.candidates||[]);annotatePositions(a.positions||[])},0)}
function fetchState(){fetch('/api/coin/state',{cache:'no-store'}).then(r=>r.ok?r.json():null).then(d=>d&&apply(d)).catch(()=>{})}
if(!window.__NAMUH_V360_COIN_FETCH__){window.__NAMUH_V360_COIN_FETCH__=true;const native=window.fetch.bind(window);window.fetch=async(...args)=>{const res=await native(...args);try{const u=String(args?.[0] instanceof Request?args[0].url:args?.[0]||'');if(u.includes('/api/coin/state'))res.clone().json().then(apply).catch(()=>{})}catch(_){}return res}}
function init(){ensureStyle();ensureFilters();fetchState()}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});else init();
})();
