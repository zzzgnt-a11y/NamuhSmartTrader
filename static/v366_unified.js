(()=>{
'use strict';
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[c]));
const num=v=>{const n=Number(String(v??0).replace(/,/g,''));return Number.isFinite(n)?n:0};
let searchMode='';

function placeSearch(force=false){
  const box=document.getElementById('v34SearchBox');
  if(!box)return;
  const mobile=window.innerWidth<=780;
  const nextMode=mobile?'mobile':'desktop';
  if(!force&&searchMode===nextMode)return;
  searchMode=nextMode;
  if(mobile){
    const page=document.querySelector('main.page');
    const hero=document.getElementById('homeSec')||page?.firstElementChild;
    if(page&&hero&&box.parentNode!==page)page.insertBefore(box,hero);
    else if(page&&hero&&box.nextElementSibling!==hero)page.insertBefore(box,hero);
    box.classList.add('v366-mobile-search');
  }else{
    box.classList.remove('v366-mobile-search');
    const strip=document.querySelector('.control-strip');
    const budget=strip?.querySelector('.budget-control');
    if(strip&&box.parentNode!==strip)strip.insertBefore(box,budget||strip.firstChild);
  }
}

function dedupeCoinCalendars(){
  if(!document.body.classList.contains('coin-body'))return;
  const main=document.querySelector('main.coin-page, main.page');
  if(!main)return;
  const sections=[...main.querySelectorAll('section')].filter(sec=>{
    if(sec.id==='coinCalendarSec')return true;
    const title=sec.querySelector('h2')?.textContent?.replace(/\s+/g,' ').trim()||'';
    return title.includes('코인 손익 캘린더');
  });
  if(sections.length<=1)return;
  const keep=sections.find(x=>x.id==='coinCalendarSec')||sections[0];
  sections.forEach(x=>{if(x!==keep)x.remove()});
}

function activeStockMarket(){
  return document.getElementById('usModeLabel')?.classList.contains('active')?'US':'KR';
}
function stateNow(){
  try{return typeof STATE!=='undefined'?STATE:null}catch(_){return null}
}
function moneyKRW(v){
  const n=Math.round(num(v));
  return '₩'+n.toLocaleString('ko-KR');
}
function pnlKRW(v){
  const n=Math.round(num(v));
  return '₩'+(n<0?'-':'')+Math.abs(n).toLocaleString('ko-KR');
}
function percent(v){
  const n=num(v);return (n>=0?'+':'')+n.toFixed(2)+'%';
}
function tradePrice(v,m){
  const n=num(v);
  return m==='US'?'$'+n.toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:4}):Math.round(n).toLocaleString('ko-KR')+'원';
}
function marketOf(t,fallback){
  const m=String(t?.market||t?.market_type||'').toUpperCase();
  if(m==='KR'||m==='US')return m;
  return fallback;
}
function stockTradeCard(t,m){
  const side=String(t?.side||'').toUpperCase()==='BUY'?'BUY':'SELL';
  const sell=side==='SELL';
  const q=num(t?.qty);
  const qty=q.toLocaleString('ko-KR',{maximumFractionDigits:6});
  const reason=[String(t?.strategy_display||t?.strategy||'').replace(/^SCALP$/,'조건1').trim(),String(t?.reason||'').trim()].filter((x,i,a)=>x&&a.indexOf(x)===i).join(' · ');
  const pnl=num(t?.pnl),pp=num(t?.pnl_pct);
  return `<article class="v367-stock-trade-card ${sell?'sell':'buy'}">
    <div class="v367-stock-trade-top">
      <span class="v367-stock-side">${side}</span>
      <div class="v367-stock-name"><b>${esc(t?.name||t?.code||'-')}</b><small>${esc(t?.code||'')} · ${esc(t?.date||'')} ${esc(t?.time||'')} KST</small></div>
      <strong class="v367-stock-qty">${qty}<em>주</em></strong>
    </div>
    <div class="v367-stock-detail">
      <div class="v367-stock-detail-qty"><small>수량</small><b>${qty}주</b></div>
      <div><small>${sell?'매도가':'매수가'}</small><b>${tradePrice(t?.price,m)}</b></div>
      <div><small>${sell?'매도금액':'매수금액'}</small><b>${moneyKRW(t?.gross_krw||0)}</b></div>
    </div>
    <div class="v367-stock-foot"><small>${esc(reason||'체결')}</small>${sell?`<b class="${pnl>=0?'pos':'neg'}">${pnlKRW(pnl)} · ${percent(pp)}</b>`:'<b class="v367-stock-buy-done">매수 체결</b>'}</div>
  </article>`;
}
function prettyStockTrades(){
  if(document.body.classList.contains('coin-body'))return;
  const box=document.getElementById('v364Trades');
  const filterBox=document.getElementById('v364Filter');
  if(!box||!filterBox)return;
  const st=stateNow();
  const all=st?.paper?.trades||st?.account?.trades;
  if(!Array.isArray(all))return;
  const m=activeStockMarket();
  const f=filterBox.querySelector('button.active')?.dataset.f||'ALL';
  const rows=all.filter(t=>marketOf(t,m)===m&&(f==='ALL'||String(t?.side||'').toUpperCase()===f)).slice(0,100);
  const key=m+'|'+f+'|'+rows.map(t=>[t.side,t.code,t.qty,t.price,t.date,t.time,t.strategy_display,t.strategy,t.reason,t.pnl,t.pnl_pct,t.gross_krw].join(':')).join('|');
  if(box.dataset.v367Key===key&&box.querySelector('.v367-stock-trade-card'))return;
  box.dataset.v367Key=key;
  box.classList.add('v367-pretty-stock');
  box.innerHTML=rows.length?rows.map(t=>stockTradeCard(t,m)).join(''):`<div class="v364-empty">${m==='US'?'미장':'국장'} ${f==='BUY'?'매수':f==='SELL'?'매도':''} 내역이 없습니다.</div>`;
}

let queued=false;
function later(){
  if(queued)return;queued=true;
  requestAnimationFrame(()=>requestAnimationFrame(()=>{queued=false;dedupeCoinCalendars();prettyStockTrades()}));
}
function installObservers(){
  const coinMain=document.querySelector('main.coin-page');
  if(coinMain){
    const obs=new MutationObserver(()=>later());
    obs.observe(coinMain,{childList:true,subtree:false});
  }
  const trade=document.getElementById('v364Trades');
  if(trade){
    const obs=new MutationObserver(()=>later());
    obs.observe(trade,{childList:true,subtree:false});
  }
}
function init(){
  placeSearch(true);dedupeCoinCalendars();prettyStockTrades();
  setTimeout(()=>{placeSearch(true);dedupeCoinCalendars();prettyStockTrades();installObservers()},100);
  setTimeout(()=>{dedupeCoinCalendars();prettyStockTrades()},350);
  let resizeTimer=0;
  window.addEventListener('resize',()=>{clearTimeout(resizeTimer);resizeTimer=setTimeout(()=>placeSearch(false),160)},{passive:true});
  document.addEventListener('click',e=>{
    if(e.target?.closest?.('#v364Filter button,#krModeLabel,#usModeLabel'))setTimeout(prettyStockTrades,0);
  },true);
  setInterval(()=>{dedupeCoinCalendars();prettyStockTrades()},1200);
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});else init();
})();