(()=>{
'use strict';
const $=s=>document.querySelector(s);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[c]));
let latest=[],filter='ALL',lastKey='',lastMarket='KR';

function market(){return $('#usModeLabel')?.classList.contains('active')?'US':'KR'}
function won(n){const v=Math.round(Number(n||0));return (v<0?'-':'')+Math.abs(v).toLocaleString('ko-KR')+'원'}
function price(n,m){const v=Number(n||0);return m==='US'?'$'+v.toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:4}):Math.round(v).toLocaleString('ko-KR')+'원'}
function pct(n){const v=Number(n||0);return (v>=0?'+':'')+v.toFixed(2)+'%'}
function qty(n){return Math.max(0,Number(n||0)).toLocaleString('ko-KR',{maximumFractionDigits:8})+'주'}
function strategy(t){const s=String(t?.strategy_display||t?.strategy||'').trim();return s==='SCALP'?'조건1':s}

function ensureControls(){
  const sec=$('#tradeSec'); if(!sec)return;
  const head=sec.querySelector('.section-head'); if(!head)return;
  let box=head.querySelector('.v360-trade-controls');
  if(!box){
    const old=head.querySelector(':scope > b'); if(old)old.remove();
    box=document.createElement('div');box.className='v360-trade-controls';
    box.innerHTML='<span class="v360-trade-scope"></span><button data-trade-filter="ALL" class="active">전체</button><button data-trade-filter="BUY">매수</button><button data-trade-filter="SELL">매도</button>';
    head.appendChild(box);
    box.addEventListener('click',e=>{const b=e.target.closest('[data-trade-filter]');if(!b)return;filter=b.dataset.tradeFilter;box.querySelectorAll('button').forEach(x=>x.classList.toggle('active',x===b));render()});
  }
  const scope=box.querySelector('.v360-trade-scope');if(scope)scope.textContent=(lastMarket==='US'?'미장':'국장')+' 모의매매';
}
function ensureStyle(){
 if($('#v360Style'))return;
 const s=document.createElement('style');s.id='v360Style';s.textContent=`
 .v360-trade-controls{margin-left:auto;display:flex;align-items:center;justify-content:flex-end;gap:6px;flex-wrap:wrap}
 .v360-trade-controls span{font-size:10px;font-weight:800;opacity:.7;margin-right:2px}
 .v360-trade-controls button{border:1px solid rgba(68,100,160,.18);background:rgba(255,255,255,.55);border-radius:999px;padding:5px 9px;font-size:10px;font-weight:800;cursor:pointer}
 .v360-trade-controls button.active{background:rgba(55,95,190,.12);border-color:rgba(55,95,190,.34)}
 @media(max-width:640px){.v360-trade-controls span{display:none}.v360-trade-controls{gap:4px}.v360-trade-controls button{padding:4px 7px;font-size:9px}}
 `;document.head.appendChild(s)
}
function render(){
  ensureControls();const box=$('#stockTrades');if(!box)return;
  const rows=latest.filter(t=>filter==='ALL'||String(t.side||'').toUpperCase()===filter).slice(0,100);
  const key=lastMarket+'|'+filter+'|'+rows.map(t=>[t.side,t.code,t.qty,t.price,t.date,t.time,t.strategy_display,t.strategy,t.reason,t.pnl,t.pnl_pct].join(':')).join('|');
  if(key===lastKey&&box.dataset.v360==='1')return;lastKey=key;box.dataset.v360='1';
  box.innerHTML=rows.length?rows.map(t=>{
    const side=String(t.side||'').toUpperCase(),st=strategy(t),reason=String(t.reason||'').trim();
    const detail=[st,reason&&reason!==st?reason:''].filter(Boolean).join(' · ');
    const pnl=Number(t.pnl||0),pp=Number(t.pnl_pct||0),unit=side==='BUY'?'매수가':'매도가';
    const amount=side==='SELL'?`${won(pnl)} · ${pct(pp)}`:`매수금액 ${won(t.gross_krw)}`;
    return `<div class="stock-trade-row"><div><span class="trade-side ${side==='BUY'?'buy':'sell'}">${side==='BUY'?'매수':'매도'}</span><b>${esc(t.name||t.code)}</b><small>${esc(t.date||'')} ${esc(t.time||'')}${detail?' · '+esc(detail):''}</small></div><div><b>${unit} ${price(t.price,lastMarket)} · ${qty(t.qty)}</b><small class="${pnl>=0?'pos':'neg'}">${amount}</small></div></div>`;
  }).join(''):`<div class="empty">${lastMarket==='US'?'미장':'국장'} ${filter==='BUY'?'매수':filter==='SELL'?'매도':''} 내역이 없습니다.</div>`;
}
function applyState(d){
  const m=String(d?.mode||market()).toUpperCase();if(m!=='KR'&&m!=='US')return;
  lastMarket=m;latest=Array.isArray(d?.paper?.trades)?d.paper.trades.filter(t=>String(t.market||m).toUpperCase()===m):[];
  const title=$('#scalpTitle');if(title)title.textContent=m==='US'?'미장 단타 탐지':'국장 단타 탐지';
  render();
}
function fetchState(){
  const m=market();fetch(`/api/state?market=${m}`,{cache:'no-store'}).then(r=>r.ok?r.json():null).then(d=>d&&applyState(d)).catch(()=>{})
}
function sectorFallbackClick(e){
  const row=e.target.closest?.('#sectorMemberList .sector-member');if(!row||row.dataset.stock)return;
  const m=market(),small=row.querySelector('small')?.textContent||'',code=(m==='KR'?(small.match(/\b\d{6}\b/)||[])[0]:(small.match(/\b[A-Z][A-Z0-9.\-]{0,9}\b/)||[])[0]);
  if(!code)return;
  e.preventDefault();e.stopPropagation();
  const name=row.querySelector('b')?.textContent||code;
  try{fetch(`/api/v348/track/${encodeURIComponent(m)}/${encodeURIComponent(code)}?name=${encodeURIComponent(name)}`,{method:'POST',cache:'no-store',keepalive:true}).catch(()=>{})}catch(_){}
  location.assign(`/stock/${encodeURIComponent(m)}/${encodeURIComponent(code)}`);
}
function init(){
  ensureStyle();ensureControls();
  document.addEventListener('click',sectorFallbackClick,true);
  ['#krModeLabel','#usModeLabel'].forEach(s=>$(s)?.addEventListener('click',()=>setTimeout(fetchState,80)));
  fetchState();
}
if(!window.__NAMUH_V360_STATE_FETCH__){
 window.__NAMUH_V360_STATE_FETCH__=true;const native=window.fetch.bind(window);
 window.fetch=async(...args)=>{const res=await native(...args);try{const u=String(args?.[0] instanceof Request?args[0].url:args?.[0]||'');if(u.includes('/api/state'))res.clone().json().then(d=>setTimeout(()=>applyState(d),0)).catch(()=>{})}catch(_){}return res};
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});else init();
})();
