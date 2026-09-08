(()=>{
'use strict';

// Function-only layer. It intentionally creates no new sections, moves no controls,
// and changes no layout/CSS. Existing containers are only filled with more reliable
// server-side ledger/score data.
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[c]));
const num=v=>{const n=Number(v);return Number.isFinite(n)?n:0};
const won=v=>`${Math.round(num(v))<0?'-':''}${Math.abs(Math.round(num(v))).toLocaleString('ko-KR')}원`;
const signedWon=v=>{const n=Math.round(num(v));return `${n>0?'+':n<0?'-':''}${Math.abs(n).toLocaleString('ko-KR')}원`};
const pct=v=>`${num(v)>=0?'+':''}${num(v).toFixed(2)}%`;
const LEDGER={KR:null,US:null,COIN:null};
let ledgerBusy=false,scoreBusy=false,calendarGuard=false,scoreData=null;

function currentMarket(){
  const b=String(document.body?.dataset?.market||'').toUpperCase();
  if(b==='KR'||b==='US'||b==='COIN')return b;
  if(location.pathname.startsWith('/coin'))return 'COIN';
  if(document.querySelector('#usModeLabel.active'))return 'US';
  return 'KR';
}
function mainPage(){return location.pathname==='/'||location.pathname==='/index.html'}
function coinPage(){return location.pathname==='/coin'||location.pathname==='/coin/'}
function stockDetail(){return location.pathname.startsWith('/stock/')}
function coinDetail(){return /^\/coin\/[^/]+/.test(location.pathname)}
function dayMap(m){return LEDGER[m]?.day_map||{}}

async function loadLedger(force=false){
  if(ledgerBusy||document.hidden)return;
  const m=currentMarket();
  if(!mainPage()&&!coinPage())return;
  ledgerBusy=true;
  try{
    const r=await fetch(`/api/v367/ledger?market=${encodeURIComponent(m)}`,{cache:'no-store'});
    if(!r.ok)throw new Error(`ledger ${r.status}`);
    LEDGER[m]=await r.json();
    patchCalendar(m);
  }catch(e){if(force)console.warn('v367 ledger',e)}finally{ledgerBusy=false}
}

function patchCalendar(m=currentMarket()){
  if(calendarGuard)return;
  const map=dayMap(m); if(!map)return;
  calendarGuard=true;
  try{
    if(m==='COIN'){
      const root=document.getElementById('coinCalendar');
      root?.querySelectorAll('[data-coin-date]').forEach(btn=>{
        const d=map[btn.dataset.coinDate]; if(!d)return;
        const p=btn.querySelector('.pnl');
        if(p){const t=signedWon(d.realized_pnl);if(p.textContent!==t)p.textContent=t;}
        btn.title=`00:00 KST 기준 · 당일 ${signedWon(d.realized_pnl)} · 누적 ${signedWon(d.cumulative_pnl)}`;
      });
    }else{
      const root=document.getElementById('profitCalendar');
      root?.querySelectorAll('[data-date]').forEach(btn=>{
        const d=map[btn.dataset.date]; if(!d)return;
        const p=btn.querySelector('.p');
        if(p){const t=signedWon(d.realized_pnl);if(p.textContent!==t)p.textContent=t;p.classList.toggle('pos',num(d.realized_pnl)>=0);p.classList.toggle('neg',num(d.realized_pnl)<0);}
        btn.title=`00:00 KST 기준 · 당일 ${signedWon(d.realized_pnl)} · 누적 ${signedWon(d.cumulative_pnl)}`;
      });
    }
  }finally{calendarGuard=false}
}

function symbolRows(d){
  const rows=Array.isArray(d?.symbols)?d.symbols.slice():[];
  if(rows.length)return rows.sort((a,b)=>Math.abs(num(b.realized_pnl))-Math.abs(num(a.realized_pnl)));
  const map={};
  for(const t of (d?.sells||[])){
    const c=String(t.code||'-'),x=map[c]||(map[c]={code:c,name:t.name||c,realized_pnl:0,sell_count:0});
    x.realized_pnl+=num(t.pnl);x.sell_count++;
  }
  return Object.values(map).sort((a,b)=>Math.abs(num(b.realized_pnl))-Math.abs(num(a.realized_pnl)));
}

function renderStockDay(date){
  const m=currentMarket(),d=dayMap(m)[date]; if(!d)return;
  const sum=document.getElementById('profitSummary'),box=document.getElementById('profitDetailList');
  if(sum)sum.textContent=`${date} · 00:00 KST 기준 · 당일 실현손익 ${signedWon(d.realized_pnl)} · 누적 ${signedWon(d.cumulative_pnl)} · 매도 ${num(d.sell_count)}건`;
  if(box){
    const rows=symbolRows(d);
    box.innerHTML=rows.length?rows.map(x=>`<div class="profit-row"><div><b>${esc(x.name||x.code)}</b><br><small>${esc(x.code||'')} · 실현매도 ${num(x.sell_count)}건</small></div><div><b class="${num(x.realized_pnl)>=0?'pos':'neg'}">${signedWon(x.realized_pnl)}</b><br><small>당일 종목별 실현손익</small></div></div>`).join(''):'<div class="empty">이 날짜의 실현 매도손익 없음</div>';
  }
}

function renderCoinDay(date){
  const d=dayMap('COIN')[date]; if(!d)return;
  const sum=document.getElementById('coinDaySummary'),box=document.getElementById('coinDayList');
  if(sum)sum.textContent=`${date} · 00:00 KST 기준 · 당일 실현손익 ${signedWon(d.realized_pnl)} · 누적 ${signedWon(d.cumulative_pnl)} · 매도 ${num(d.sell_count)}건`;
  if(box){
    const rows=symbolRows(d);
    box.innerHTML=rows.length?rows.map(x=>`<div class="coin-day-row"><div><b>${esc(x.name||x.code)}</b><br><small>${esc(x.code||'')} · 실현매도 ${num(x.sell_count)}건</small></div><div><b class="${num(x.realized_pnl)>=0?'pos':'neg'}">${signedWon(x.realized_pnl)}</b><br><small>당일 종목별 실현손익</small></div></div>`).join(''):'<div class="empty">이 날짜의 실현 매도손익 없음</div>';
  }
}

function bindCalendarClicks(){
  document.addEventListener('click',e=>{
    const s=e.target.closest?.('#profitCalendar [data-date]');
    if(s){const date=s.dataset.date;setTimeout(()=>renderStockDay(date),0);return;}
    const c=e.target.closest?.('#coinCalendar [data-coin-date]');
    if(c){const date=c.dataset.coinDate;setTimeout(()=>renderCoinDay(date),0);}
  },true);
}

function observeCalendars(){
  const install=id=>{
    const root=document.getElementById(id);if(!root)return;
    new MutationObserver(()=>{if(!calendarGuard)queueMicrotask(()=>patchCalendar(currentMarket()))}).observe(root,{childList:true,subtree:true});
  };
  install('profitCalendar');install('coinCalendar');
}

async function loadScorePipeline(){
  if(scoreBusy||document.hidden||(!stockDetail()&&!coinDetail()))return;
  const p=location.pathname.split('/').filter(Boolean),m=stockDetail()?String(p[1]||'KR').toUpperCase():'COIN',code=stockDetail()?String(p[2]||'').toUpperCase():String(p[1]||'').toUpperCase();
  if(!code)return;
  scoreBusy=true;
  try{
    const r=await fetch(`/api/v367/score-pipeline?market=${encodeURIComponent(m)}&code=${encodeURIComponent(code)}`,{cache:'no-store'});
    if(!r.ok)throw new Error(`pipeline ${r.status}`);
    const d=await r.json(); if(!d.ok||!d.pipeline)return;
    scoreData=d;renderScorePipeline();
  }catch(_){ }finally{scoreBusy=false}
}

function renderScorePipeline(){
  const p=scoreData?.pipeline;if(!p)return;
  if(stockDetail()){
    const box=document.getElementById('breakdown');if(!box)return;
    box.querySelectorAll('[data-v367-pipeline]').forEach(x=>x.remove());
    const rows=[['원시 데이터 합산',p.component_total],['정규화/게이트 보정',p.normalization_adjustment],['최종 AI 점수',p.final_score]];
    for(const [label,v] of rows){
      const d=document.createElement('div');d.className='break-row';d.dataset.v367Pipeline='1';
      d.innerHTML=`<span>${esc(label)}</span><div><i style="width:${Math.min(100,Math.abs(num(v)))}%"></i></div><b>${num(v).toFixed(1)}</b>`;box.appendChild(d);
    }
    const score=document.querySelector('#scoreGrid .score-tile.active strong');if(score)score.title=`원시합산 ${num(p.component_total).toFixed(1)} + 보정 ${num(p.normalization_adjustment).toFixed(1)} = 최종 ${num(p.final_score).toFixed(1)} · 진입기준 ${num(p.entry_threshold).toFixed(1)}`;
  }else if(coinDetail()){
    const box=document.getElementById('coinSnapshot');if(!box)return;
    box.querySelectorAll('[data-v367-pipeline]').forEach(x=>x.remove());
    const rows=[['AI 원시합산',p.component_total],['AI 보정',p.normalization_adjustment],['AI 최종점수',p.final_score],['진입기준',p.entry_threshold]];
    for(const [label,v] of rows){
      const d=document.createElement('div');d.dataset.v367Pipeline='1';d.innerHTML=`<span>${esc(label)}</span><b>${num(v).toFixed(1)}</b>`;box.appendChild(d);
    }
  }
}

function observeScoreContainers(){
  const id=stockDetail()?'breakdown':coinDetail()?'coinSnapshot':null;if(!id)return;
  const root=document.getElementById(id);if(!root)return;
  let busy=false;
  new MutationObserver(()=>{if(busy||!scoreData)return;busy=true;queueMicrotask(()=>{try{renderScorePipeline()}finally{busy=false}})}).observe(root,{childList:true});
}

function watchMode(){
  if(!document.body)return;
  new MutationObserver(muts=>{
    if(muts.some(x=>x.attributeName==='data-market')){loadLedger(true);setTimeout(()=>patchCalendar(currentMarket()),50);}
  }).observe(document.body,{attributes:true,attributeFilter:['data-market']});
}

function init(){
  bindCalendarClicks();observeCalendars();observeScoreContainers();watchMode();
  loadLedger(true);loadScorePipeline();
  setInterval(()=>{loadLedger(false);loadScorePipeline();},10000);
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});else init();
})();
