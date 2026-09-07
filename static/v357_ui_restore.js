/* Final minimal UI owner: Alice + stable KR title + separate KR trade history */
(()=>{
  const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[c]));
  const won=n=>Math.round(Number(n||0)).toLocaleString('ko-KR')+'원';
  const pct=n=>(Number(n||0)>=0?'+':'')+Number(n||0).toFixed(2)+'%';
  const price=n=>Math.round(Number(n||0)).toLocaleString('ko-KR')+'원';
  const qty=n=>Math.max(0,Number(n||0)).toLocaleString('ko-KR',{maximumFractionDigits:8})+'주';
  const strategy=t=>{
    const s=String(t?.strategy||'').trim();
    return s==='SCALP'?'조건1':s;
  };
  let latestTrades=[];
  let lastTradeKey='';

  function ensureTradeSection(){
    if(document.getElementById('tradeSec'))return;
    const holding=document.getElementById('holdingSec');
    const profit=document.getElementById('profitSec');
    if(!holding||!profit)return;
    const sec=document.createElement('section');
    sec.id='tradeSec';
    sec.className='section-shell';
    sec.innerHTML=`
      <div class="section-head"><div><span class="section-index">05</span><div><small>TRADE HISTORY</small><h2>거래내역</h2></div></div><b>국장 모의매매 내역</b></div>
      <div id="stockTrades" class="stock-trade-list"></div>`;
    profit.parentNode.insertBefore(sec,profit);
    const profitIndex=profit.querySelector('.section-index');
    if(profitIndex)profitIndex.textContent='06';
    if(!document.getElementById('stockTradeStyle')){
      const style=document.createElement('style');style.id='stockTradeStyle';
      style.textContent=`
        .stock-trade-list{display:grid;gap:8px}
        .stock-trade-row{display:flex;align-items:center;justify-content:space-between;gap:14px;padding:13px 14px;border-radius:16px;background:rgba(255,255,255,.62);border:1px solid rgba(37,73,124,.12)}
        .stock-trade-row>div{min-width:0}.stock-trade-row>div:last-child{text-align:right;flex:0 0 auto}
        .stock-trade-row b{font-size:11px}.stock-trade-row small{display:block;margin-top:4px;font-size:8px;color:#70809b;line-height:1.45}
        .trade-side{display:inline-flex;align-items:center;justify-content:center;min-width:38px;margin-right:7px;padding:4px 6px;border-radius:8px;font-size:8px;font-weight:900}
        .trade-side.buy{background:rgba(0,152,108,.09);color:#00986c}.trade-side.sell{background:rgba(224,72,100,.09);color:#e04864}
      `;
      document.head.appendChild(style);
    }
  }

  function renderTrades(trades){
    latestTrades=Array.isArray(trades)?trades:[];
    ensureTradeSection();
    const box=document.getElementById('stockTrades');if(!box)return;
    const rows=latestTrades.slice(0,80);
    const key=rows.map(t=>[t.side,t.code,t.qty,t.price,t.date,t.time,t.strategy,t.reason,t.pnl,t.pnl_pct].join(':')).join('|');
    if(key===lastTradeKey&&box.dataset.rendered==='1')return;
    lastTradeKey=key;box.dataset.rendered='1';
    box.innerHTML=rows.length?rows.map(t=>{
      const side=String(t.side||'').toUpperCase();
      const st=strategy(t);
      const reason=String(t.reason||'').trim();
      const detail=[st,reason&&reason!==st?reason:''].filter(Boolean).join(' · ');
      const pnl=Number(t.pnl||0),pp=Number(t.pnl_pct||0);
      const unitLabel=side==='BUY'?'매수가':'매도가';
      const amountLine=side==='SELL'?`${won(pnl)} · ${pct(pp)}`:`매수금액 ${won(t.gross_krw)}`;
      return `<div class="stock-trade-row"><div><span class="trade-side ${side==='BUY'?'buy':'sell'}">${esc(side)}</span><b>${esc(t.name||t.code)}</b><small>${esc(t.date||'')} ${esc(t.time||'')}${detail?' · '+esc(detail):''}</small></div><div><b>${unitLabel} ${price(t.price)} · ${qty(t.qty)}</b><small class="${pnl>=0?'pos':'neg'}">${amountLine}</small></div></div>`;
    }).join(''):'<div class="empty">아직 국장 모의매매 내역이 없습니다.</div>';
  }

  function apply(){
    const subtitle=document.getElementById('subtitle');
    if(subtitle){subtitle.textContent='with Alice';subtitle.style.display='';}
    const krActive=document.getElementById('krModeLabel')?.classList.contains('active');
    if(!krActive)return;
    const title=document.getElementById('scalpTitle');
    if(title&&title.textContent!=='국장 단타 탐지')title.textContent='국장 단타 탐지';
    ensureTradeSection();
    renderTrades(latestTrades);
  }

  if(!window.__NAMUH_TRADE_FETCH_WRAPPED__){
    window.__NAMUH_TRADE_FETCH_WRAPPED__=true;
    const nativeFetch=window.fetch.bind(window);
    window.fetch=async(...args)=>{
      const res=await nativeFetch(...args);
      try{
        const u=String(args?.[0] instanceof Request?args[0].url:args?.[0]||'');
        if(u.includes('/api/state')){
          res.clone().json().then(d=>{
            if(document.getElementById('krModeLabel')?.classList.contains('active'))renderTrades(d?.paper?.trades||[]);
          }).catch(()=>{});
        }
      }catch(_){}
      return res;
    };
  }

  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',apply,{once:true});else apply();
  document.getElementById('krModeLabel')?.addEventListener('click',()=>requestAnimationFrame(apply));
})();
