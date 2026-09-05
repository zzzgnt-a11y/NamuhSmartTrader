(function(){
  const q=s=>document.querySelector(s);
  const won=n=>'₩'+Math.round(Number(n||0)).toLocaleString('ko-KR');
  const pct=n=>(Number(n||0)>=0?'+':'')+Number(n||0).toFixed(2)+'%';
  const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[c]));
  const fmtPrice=n=>{const v=Number(n||0);return v>=1000?won(v):v.toLocaleString(undefined,{maximumFractionDigits:8})+'원'};
  let cursor=new Date();

  function normalizeHero(){
    const health=q('#coinHealth')?.parentElement;
    if(health){health.style.display='none';q('.coin-console .hero-metrics')?.classList.add('v33-metrics-3')}
    const b=q('#heroCoinBudget')?.parentElement?.querySelector('span');if(b)b.textContent='운용자산';
    const p=q('#coinPnl')?.parentElement?.querySelector('span');if(p)p.textContent='손익';
    const s=q('#coinTopSignal')?.parentElement?.querySelector('span');if(s)s.textContent='신호';
  }

  window.posRow=function(p){
    return `<div class="position-row" data-coin="${esc(p.code)}"><div><b>${esc(p.name||p.code)}</b> <span class="market-badge">COIN</span> <span class="strategy-tag">${esc(p.strategy||'COIN_SCALP')}</span><br><small>${esc(p.code)} · ${Number(p.qty||0).toLocaleString(undefined,{maximumFractionDigits:8})}개 · 24H</small><div class="v33-position-prices"><span>평균매수가 <b>${fmtPrice(p.avg_price)}</b></span><span>현재가 <b>${fmtPrice(p.current_price)}</b></span></div></div><div class="position-right"><b class="${Number(p.pnl||0)>=0?'pos':'neg'}">${pct(p.pnl_pct)}</b><br><small>평가손익 ${won(p.pnl)}</small></div></div>`;
  };

  window.tradeRow=function(t){
    const sell=String(t.side||'').toUpperCase()==='SELL';
    const buyPrice=t.buy_price??(!sell?t.price:null),sellPrice=t.sell_price??(sell?t.price:null);
    const buyAmount=t.buy_amount??(!sell?t.gross_krw:null),sellAmount=t.sell_amount??(sell?t.gross_krw:null);
    return `<div class="coin-trade-row v33-trade-row"><div class="v33-trade-main"><span class="trade-side ${sell?'sell':'buy'}">${esc(t.side)}</span><b>${esc(t.name||t.code)}</b><small>${esc(t.date)} ${esc(t.time)} · ${esc(t.reason||t.strategy||'')}</small><div class="v33-trade-grid"><span>체결가 <b>${fmtPrice(t.price)}</b></span><span>매수가 <b>${buyPrice==null?'-':fmtPrice(buyPrice)}</b></span><span>매도가 <b>${sellPrice==null?'-':fmtPrice(sellPrice)}</b></span><span>매수금액 <b>${buyAmount==null?'-':won(buyAmount)}</b></span><span>매도금액 <b>${sellAmount==null?'-':won(sellAmount)}</b></span><span>실현손익 <b class="${Number(t.pnl||0)>=0?'pos':'neg'}">${sell?won(t.pnl):'-'}${sell?' · '+pct(t.pnl_pct):''}</b></span></div></div></div>`;
  };

  function injectGlobalState(){
    const strip=q('.coin-control-strip');if(!strip||q('#coinGlobalState'))return;
    const b=document.createElement('div');b.id='coinGlobalState';b.className='control-stat v33-coin-global';
    b.innerHTML='<small>MASTER AUTO</small><strong id="coinGlobalStateText">확인 중</strong><span>전체 스위치는 주식 화면에서 변경 · OFF여도 청산 관리 계속</span>';
    strip.appendChild(b);
  }

  async function loadGlobal(){
    try{const r=await fetch('/api/trading-control',{cache:'no-store'});if(!r.ok)return;const d=await r.json();const e=Boolean(d.new_entries_enabled);const el=q('#coinGlobalStateText');if(el){el.textContent=e?'ON · 신규매수 허용':'OFF · 신규매수 중지';el.className=e?'pos':'neg'}}catch(e){console.error(e)}
  }

  function injectCalendar(){
    const main=q('main.coin-page');if(!main||q('#coinProfitSec'))return;
    const sec=document.createElement('section');sec.id='coinProfitSec';sec.className='section-shell calendar-shell v33-coin-calendar';
    sec.innerHTML='<div class="section-head"><div><span class="section-index">05</span><div><small>COIN REALIZED PNL</small><h2>코인 손익 캘린더</h2></div></div><b id="coinCalendarTotal">-</b></div><div class="calendar-main"><div class="calendar-toolbar"><button id="coinPrevMonth">‹</button><strong id="coinMonthTitle">-</strong><button id="coinNextMonth">›</button></div><div class="weekday-row"><div>일</div><div>월</div><div>화</div><div>수</div><div>목</div><div>금</div><div>토</div></div><div id="coinPnlCalendar" class="calendar-grid"></div><div id="coinPnlDetail" class="v33-calendar-detail">날짜를 누르면 코인 실현손익을 표시합니다.</div></div>';
    main.appendChild(sec);
    q('#coinPrevMonth').addEventListener('click',()=>{cursor=new Date(cursor.getFullYear(),cursor.getMonth()-1,1);loadCalendar()});
    q('#coinNextMonth').addEventListener('click',()=>{cursor=new Date(cursor.getFullYear(),cursor.getMonth()+1,1);loadCalendar()});
    const dock=q('.coin-dock');if(dock&&!q('[data-scroll="coinProfitSec"]')){const b=document.createElement('button');b.dataset.scroll='coinProfitSec';b.innerHTML='◫<small>손익</small>';b.addEventListener('click',()=>q('#coinProfitSec')?.scrollIntoView({behavior:'smooth'}));dock.appendChild(b)}
  }

  async function loadCalendar(){
    const y=cursor.getFullYear(),m=cursor.getMonth()+1;
    q('#coinMonthTitle').textContent=`${y}년 ${m}월`;
    try{
      const r=await fetch(`/api/pnl-calendar?scope=coin&year=${y}&month=${m}`,{cache:'no-store'});const d=await r.json();if(!r.ok)throw new Error(d.detail||r.status);
      q('#coinCalendarTotal').textContent=`월 실현손익 ${won(d.total_pnl||0)}`;
      const first=new Date(y,m-1,1),last=new Date(y,m,0),cells=[];for(let i=0;i<first.getDay();i++)cells.push(null);for(let day=1;day<=last.getDate();day++)cells.push(day);
      q('#coinPnlCalendar').innerHTML=cells.map(day=>{if(!day)return '<div></div>';const k=`${y}-${String(m).padStart(2,'0')}-${String(day).padStart(2,'0')}`,v=d.days?.[k];return `<button class="day-cell" data-coin-day="${k}"><div class="d">${day}</div><div class="p ${v?(Number(v.pnl)>=0?'pos':'neg'):''}">${v?won(v.pnl):''}</div></button>`}).join('');
      q('#coinPnlCalendar').querySelectorAll('[data-coin-day]').forEach(btn=>btn.addEventListener('click',()=>{const v=d.days?.[btn.dataset.coinDay];q('#coinPnlDetail').innerHTML=v?`<b>${btn.dataset.coinDay} · ${won(v.pnl)}</b>`+(v.trades||[]).map(t=>`<div class="profit-row"><span>${esc(t.name||t.code)} · ${esc(t.time||'')}</span><b class="${Number(t.pnl||0)>=0?'pos':'neg'}">${won(t.pnl)} · ${pct(t.pnl_pct)}</b></div>`).join(''):`<b>${btn.dataset.coinDay}</b><div class="empty">실현 매매 없음</div>`}))
    }catch(e){console.error(e);q('#coinPnlCalendar').innerHTML='<div class="empty">손익 캘린더 연결 대기</div>'}
  }

  normalizeHero();injectGlobalState();injectCalendar();loadGlobal();loadCalendar();
  setInterval(loadGlobal,15000);
})();
