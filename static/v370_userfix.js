(()=>{
'use strict';
let busy=false, coinCalBusy=false;
const q=s=>document.querySelector(s);
const qa=s=>[...document.querySelectorAll(s)];
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[c]));
const num=v=>{const n=Number(String(v??0).replace(/,/g,''));return Number.isFinite(n)?n:0};
const signedWon=v=>{const n=Math.round(num(v));return `${n>0?'+':n<0?'-':''}${Math.abs(n).toLocaleString('ko-KR')}원`};
const won=v=>`${Math.round(num(v)).toLocaleString('ko-KR')}원`;
const pct=v=>`${num(v)>=0?'+':''}${num(v).toFixed(2)}%`;
function todayKst(){const p=new Intl.DateTimeFormat('en-US',{timeZone:'Asia/Seoul',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(new Date()),m={};p.forEach(x=>m[x.type]=x.value);return `${m.year}-${m.month}-${m.day}`}
function currentMarket(){if(location.pathname.startsWith('/coin'))return 'COIN';if(q('#usModeLabel')?.classList.contains('active'))return 'US';return 'KR'}
function side(t){return String(t?.side||'').toUpperCase()}
function tmarket(t){const m=String(t?.market||t?.market_type||'').toUpperCase();if(['KR','US','COIN'].includes(m))return m;const c=String(t?.code||t?.symbol||'').toUpperCase();if(c.startsWith('KRW-'))return 'COIN';return /^[A-Z]/.test(c)?'US':'KR'}
function pnlOf(t){for(const k of ['pnl','realized_pnl','profit_krw','realized']){if(t?.[k]!==undefined&&t?.[k]!==null&&t?.[k]!=='')return num(t[k])}return 0}
function stockPrice(t){return String(t?.currency||'').toUpperCase()==='USD'?`$${num(t.price).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:4})}`:won(t.price)}
function coinPrice(t){const v=num(t.price);return v>=1000?won(v):`${v.toLocaleString(undefined,{maximumFractionDigits:8})}원`}
function stockRows(){try{const st=typeof STATE!=='undefined'?STATE:null;return st?.paper?.trades||st?.account?.trades||[]}catch(_){return []}}
function coinRows(){try{return typeof coinLastTrades!=='undefined'&&Array.isArray(coinLastTrades)?coinLastTrades:[]}catch(_){return []}}
function renderTodayStock(){const box=q('#v364Trades');if(!box)return;const m=currentMarket();if(m==='COIN')return;const f=q('#v364Filter button.active')?.dataset.f||'ALL',today=todayKst();const rows=stockRows().filter(t=>String(t?.date||'').slice(0,10)===today&&tmarket(t)===m&&(f==='ALL'||side(t)===f)).slice(0,100);const html=rows.map(t=>{const s=side(t),p=pnlOf(t),sell=s==='SELL',pt=sell?signedWon(p):'미실현';return `<div class="v364-trade"><div><span class="v364-side ${s==='BUY'?'buy':'sell'}">${s==='BUY'?'매수':'매도'}</span><b>${esc(t.name||t.code||'-')}</b><small>${esc(t.date||'')} ${esc(t.time||'')} · ${esc(t.reason||t.strategy||'')}</small></div><div><b>${stockPrice(t)}</b><small>체결금액 ${won(t.gross_krw||0)} · 손익금액 <span class="${sell?(p>=0?'pos':'neg'):''}">${pt}</span>${sell?` · ${pct(t.pnl_pct)}`:''}</small></div></div>`}).join('');const out=html||'<div class="v364-empty">오늘 거래내역 없음</div>';if(box.innerHTML!==out){busy=true;box.innerHTML=out;busy=false}}
function renderTodayCoin(){const box=q('#coinTrades');if(!box)return;const f=q('#coinTradeFilters button.active')?.dataset.tradeFilter||'ALL',today=todayKst();const rows=coinRows().filter(t=>String(t?.date||'').slice(0,10)===today&&(f==='ALL'||side(t)===f)).slice(0,100);const html=rows.map(t=>{const s=side(t),p=pnlOf(t),sell=s==='SELL',pt=sell?signedWon(p):'미실현';return `<div class="coin-trade-row"><div><span class="trade-side ${s==='BUY'?'buy':'sell'}">${s==='BUY'?'매수':'매도'}</span><b>${esc(t.name||t.code||'-')}</b><small>${esc(t.date||'')} ${esc(t.time||'')} · ${esc(t.reason||t.strategy||'')}</small></div><div><b>${coinPrice(t)}</b><small>체결금액 ${won(t.gross_krw||0)} · 손익금액 <span class="${sell?(p>=0?'pos':'neg'):''}">${pt}</span>${sell?` · ${pct(t.pnl_pct)}`:''}</small></div></div>`}).join('');const out=html||'<div class="empty">오늘 거래내역 없음</div>';if(box.innerHTML!==out){busy=true;box.innerHTML=out;busy=false}}
function normalizeCoinCalendar(){if(coinCalBusy)return;const sec=q('#coinCalendarSec'),cal=q('#coinCalendar');if(!sec||!cal)return;coinCalBusy=true;try{
  sec.classList.add('calendar-shell','v370-coin-calendar');
  let layout=sec.querySelector(':scope > .calendar-layout');
  if(!layout){const top=sec.querySelector('.coin-calendar-top'),sum=q('#coinDaySummary'),list=q('#coinDayList'),head=sec.querySelector('.section-head');layout=document.createElement('div');layout.className='calendar-layout';const main=document.createElement('div');main.className='calendar-main';const detail=document.createElement('aside');detail.className='calendar-detail';if(top){top.classList.add('calendar-toolbar');main.appendChild(top)}const wr=document.createElement('div');wr.className='weekday-row v370-weekdays';wr.innerHTML='<div>일</div><div>월</div><div>화</div><div>수</div><div>목</div><div>금</div><div>토</div>';main.appendChild(wr);main.appendChild(cal);detail.insertAdjacentHTML('beforeend','<small>SELECTED DAY</small>');if(sum){sum.classList.add('profit-summary');detail.appendChild(sum)}if(list)detail.appendChild(list);layout.append(main,detail);head?.after(layout)}
  cal.classList.add('calendar-grid');
  cal.querySelectorAll('.coin-cal-week').forEach(x=>x.remove());
  cal.querySelectorAll('.coin-cal-day').forEach(b=>{b.classList.add('day-cell');b.querySelector('.num')?.classList.add('d');b.querySelector('.pnl')?.classList.add('p')});
  q('#coinDayList')?.querySelectorAll('.coin-day-row').forEach(x=>x.classList.add('profit-row'));
}finally{coinCalBusy=false}}
function installStyle(){if(q('#v370UserStyle'))return;const s=document.createElement('style');s.id='v370UserStyle';s.textContent=`
.v370-coin-calendar .coin-calendar-top{margin-bottom:12px}.v370-coin-calendar .coin-cal-day{width:100%;text-align:left}.v370-coin-calendar .coin-cal-day .cnt{display:block;margin-top:5px;font-size:10px;opacity:.62}.v370-coin-calendar .coin-day-list{display:grid;gap:0}.v370-coin-calendar .coin-day-row{display:flex;justify-content:space-between;gap:12px}.v370-coin-calendar .coin-day-row>div:last-child{text-align:right}.v370-coin-calendar .v370-weekdays{margin-top:6px}
`;document.head.appendChild(s)}
function tick(){if(busy)return;renderTodayStock();renderTodayCoin();normalizeCoinCalendar()}
function init(){installStyle();tick();const obs=new MutationObserver(()=>{if(!busy&&!coinCalBusy)queueMicrotask(tick)});['#v364Trades','#coinTrades','#coinCalendar','#coinDayList'].forEach(sel=>{const el=q(sel);if(el)obs.observe(el,{childList:true,subtree:true})});document.addEventListener('click',e=>{if(e.target.closest?.('#v364Filter button,#coinTradeFilters button'))setTimeout(tick,0)},true);setInterval(tick,1200)}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});else init();
})();
