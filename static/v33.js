(function(){
  const q=s=>document.querySelector(s);
  const fmtWon=n=>(Number(n||0)>=0?'':'-')+Math.abs(Math.round(Number(n||0))).toLocaleString('ko-KR')+'원';
  const fmtPct=n=>(Number(n||0)>=0?'+':'')+Number(n||0).toFixed(2)+'%';
  const fmtPrice=(n,m)=>m==='US'?'$'+Number(n||0).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:4}):fmtWon(n);
  const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[c]));

  function normalizeHero(){
    const health=q('#health')?.parentElement;
    if(health){health.style.display='none';q('.hero-metrics')?.classList.add('v33-metrics-3')}
    const budget=q('#heroBudget')?.parentElement?.querySelector('span');if(budget)budget.textContent='운용자산';
    const pnl=q('#overallPnl')?.parentElement?.querySelector('span');if(pnl)pnl.textContent='손익';
    const sig=q('#topScalp')?.parentElement?.querySelector('span');if(sig)sig.textContent='신호';
  }

  function injectMasterToggle(){
    const strip=q('.control-strip');
    if(!strip||q('#v33MasterControl'))return;
    const box=document.createElement('div');
    box.id='v33MasterControl';box.className='v33-master-control';
    box.innerHTML='<div><small>전체 자동매매</small><strong id="v33MasterState">확인 중</strong></div><label class="v33-switch"><input id="v33MasterToggle" type="checkbox"><span></span></label><p id="v33MasterNote">OFF = 신규매수만 중지 · 기존 보유 익절/손절/청산은 계속</p>';
    strip.prepend(box);
    q('#v33MasterToggle').addEventListener('change',async e=>{
      const enabled=Boolean(e.target.checked);
      q('#v33MasterState').textContent='저장 중';
      try{
        const r=await fetch('/api/trading-control',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({new_entries_enabled:enabled})});
        const d=await r.json();if(!r.ok)throw new Error(d.detail||r.status);applyControl(d);
      }catch(err){console.error(err);await loadControl()}
    });
  }

  function applyControl(d){
    const enabled=Boolean(d?.new_entries_enabled);
    const t=q('#v33MasterToggle');if(t)t.checked=enabled;
    const s=q('#v33MasterState');if(s){s.textContent=enabled?'ON · 신규매수 허용':'OFF · 신규매수 중지';s.className=enabled?'pos':'neg'}
    const n=q('#v33MasterNote');if(n)n.textContent=(d?.persistence?.durable?'DB 저장 · ':'')+'브라우저와 무관하게 서버에서 감시 · OFF여도 보유종목 청산 관리 계속';
  }

  async function loadControl(){
    try{const r=await fetch('/api/trading-control',{cache:'no-store'});if(!r.ok)throw new Error(r.status);applyControl(await r.json())}catch(e){console.error(e)}
  }

  try{
    if(typeof window.positionRow==='function'||typeof positionRow==='function'){
      window.positionRow=function(p){
        const qty=p.market==='COIN'?Number(p.qty||0).toLocaleString(undefined,{maximumFractionDigits:8})+'개':Number(p.qty||0).toLocaleString()+'주';
        return `<div class="position-row" ${p.market==='COIN'?`data-coin="${esc(p.code)}"`:`data-stock="${esc(p.market)}/${esc(p.code)}"`}><div><b>${esc(p.name||p.code)}</b> <span class="market-badge">${esc(p.market||'-')}</span> <span class="strategy-tag">${esc(p.strategy||'SCALP')}</span><br><small>${esc(p.code)} · ${qty}</small><div class="v33-position-prices"><span>평균매수가 <b>${fmtPrice(p.avg_price,p.market)}</b></span><span>현재가 <b>${fmtPrice(p.current_price,p.market)}</b></span></div></div><div class="position-right"><b class="${Number(p.pnl||0)>=0?'pos':'neg'}">${fmtPct(p.pnl_pct)}</b><br><small>평가손익 ${fmtWon(p.pnl)}</small></div></div>`;
      };
    }
  }catch(e){console.error(e)}

  normalizeHero();injectMasterToggle();loadControl();
  setInterval(loadControl,15000);
})();
