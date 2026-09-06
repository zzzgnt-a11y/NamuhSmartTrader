(function(){
  const q=s=>document.querySelector(s),qa=s=>[...document.querySelectorAll(s)];
  const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[c]));
  const won=n=>'₩'+Math.round(Number(n||0)).toLocaleString('ko-KR');
  const pct=n=>(Number(n||0)>=0?'+':'')+Number(n||0).toFixed(2)+'%';
  const fmt=n=>{const v=Number(n||0);return v>=1000?won(v):v.toLocaleString(undefined,{maximumFractionDigits:8})+'원'};
  const fmtQty=n=>{const v=Number(n||0),a=Math.abs(v),digits=a>0&&a<1?6:(a<100?4:2);return v.toLocaleString('ko-KR',{maximumFractionDigits:digits})};
  const tradeStamp=t=>`${String(t.date||'').trim()} ${String(t.time||'').trim()} KST`.trim();

  function addWithAlice(){const h=q('.hero-copy h1');if(!h||q('.v34-with-alice'))return;const s=document.createElement('small');s.className='v34-with-alice';s.textContent='with Alice';h.appendChild(s)}

  function topAuto(){
    const top=q('.top-actions'),sw=q('.market-switch'),live=q('.live-chip');if(!top||!sw)return;
    if(!q('#v34AutoBtn')){const b=document.createElement('button');b.id='v34AutoBtn';b.className='v34-auto-btn';b.textContent='AUTO ...';b.addEventListener('click',toggle);top.insertBefore(b,sw)}
    if(live)top.appendChild(live);
    q('#coinGlobalState')?.remove();
    // Global AUTO is the only user-facing new-entry switch.
    q('.auto-toggle')?.classList.add('v34-hidden');
    load();
  }
  async function load(){try{const r=await fetch('/api/trading-control',{cache:'no-store'});const d=await r.json();const b=q('#v34AutoBtn');if(!b)return;b.dataset.enabled=String(Boolean(d.new_entries_enabled));b.textContent=d.new_entries_enabled?'AUTO ON':'AUTO OFF';b.classList.toggle('off',!d.new_entries_enabled)}catch(_){} }
  async function toggle(){const b=q('#v34AutoBtn'),next=b?.dataset.enabled!=='true';if(!b)return;b.disabled=true;try{await fetch('/api/trading-control',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({new_entries_enabled:next})});await load()}finally{b.disabled=false}}

  window.posRow=function(p){
    const qty=fmtQty(p.qty);
    return `<div class="position-row" data-coin="${esc(p.code)}"><div><b>${esc(p.name||p.code)}</b> <span class="market-badge">COIN</span> <span class="strategy-tag">${esc(p.strategy||'COIN_SCALP')}</span><br><small>${esc(p.code)} · ${qty}개 · 24H</small></div><div class="position-right"><b class="${Number(p.pnl||0)>=0?'pos':'neg'}">${pct(p.pnl_pct)}</b><br><small>${won(p.pnl)} · ${fmt(p.current_price)}</small></div></div>`;
  };

  window.tradeRow=function(t){
    const sell=String(t.side||'').toUpperCase()==='SELL',qty=fmtQty(t.qty);
    const buyPrice=t.buy_price??(!sell?t.price:null),sellPrice=t.sell_price??(sell?t.price:null),buyAmount=t.buy_amount??(!sell?t.gross_krw:null),sellAmount=t.sell_amount??(sell?t.gross_krw:null);
    return `<article class="v34-trade-card"><div class="v34-trade-title"><span class="trade-side ${sell?'sell':'buy'}">${sell?'SELL':'BUY'}</span><div><b>${esc(t.name||t.code)}</b><small>${esc(t.code)} · ${esc(tradeStamp(t))}</small></div><strong>${qty}<small>개</small></strong></div><div class="v34-trade-grid"><div><span>체결가</span><b>${fmt(t.price)}</b></div><div><span>수량</span><b>${qty}개</b></div><div><span>매수가</span><b>${buyPrice==null?'-':fmt(buyPrice)}</b></div><div><span>매도가</span><b>${sellPrice==null?'-':fmt(sellPrice)}</b></div><div><span>매수금액</span><b>${buyAmount==null?'-':won(buyAmount)}</b></div><div><span>매도금액</span><b>${sellAmount==null?'-':won(sellAmount)}</b></div></div><div class="v34-trade-pnl"><span>${esc(t.reason||t.strategy||'')}</span><b class="${Number(t.pnl||0)>=0?'pos':'neg'}">${sell?won(t.pnl)+' · '+pct(t.pnl_pct):'매수 완료'}</b></div></article>`;
  };

  function normalizeText(){
    // Display only eight market rows and eight candidates; internal scan remains broader.
    qa('#coinMarketGrid > *:nth-child(n+9),#coinCandidateList > *:nth-child(n+9)').forEach(x=>x.style.display='none');
    qa('.metric span').forEach(el=>{if(el.textContent.trim()==='스프레드')el.textContent='매수·매도 가격차'});
    const pnl=q('#coinPnl')?.parentElement?.querySelector('span');if(pnl)pnl.textContent='실현손익';
    q('#coinGlobalState')?.remove();q('.auto-toggle')?.classList.add('v34-hidden');
  }

  function init(){addWithAlice();topAuto();normalizeText();const obs=new MutationObserver(normalizeText);['#coinMarketGrid','#coinCandidateList','#coinTrades'].forEach(s=>{const el=q(s);if(el)obs.observe(el,{childList:true,subtree:true})});setInterval(load,12000);setInterval(normalizeText,1500)}
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init);else init();
})();
