(function(){
  const q=s=>document.querySelector(s), qa=s=>[...document.querySelectorAll(s)];
  const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[c]));
  const won=n=>(Number(n||0)>=0?'':'-')+Math.abs(Math.round(Number(n||0))).toLocaleString('ko-KR')+'원';
  const pct=n=>(Number(n||0)>=0?'+':'')+Number(n||0).toFixed(2)+'%';
  let searchTimer=null;

  function currentMarket(){return q('#usModeLabel')?.classList.contains('active')?'US':'KR'}

  function addWithAlice(){
    const h=q('.hero-copy h1');if(!h||q('.v34-with-alice'))return;
    const s=document.createElement('small');s.className='v34-with-alice';s.textContent='with Alice';h.appendChild(s);
  }

  function cleanHero(){
    q('#subtitle')?.classList.add('v34-hidden');
    q('#scheduleCard')?.classList.add('v34-hidden');
    const pnl=q('#overallPnl')?.parentElement?.querySelector('span');if(pnl)pnl.textContent='실현손익';
    q('#v33MasterControl')?.remove();
  }

  function normalizeTop(){
    const top=q('.top-actions'), sw=q('.market-switch'), live=q('.live-chip');
    if(!top||!sw)return;
    if(!q('#v34AutoBtn')){
      const b=document.createElement('button');b.id='v34AutoBtn';b.className='v34-auto-btn';b.textContent='AUTO ...';
      b.addEventListener('click',toggleAuto);top.insertBefore(b,sw);
    }
    if(live)top.appendChild(live); // AUTO | KR | US | COIN ........ clock at far right
    loadAuto();
  }

  async function loadAuto(){
    try{
      const r=await fetch('/api/trading-control',{cache:'no-store'});if(!r.ok)return;
      const d=await r.json(),b=q('#v34AutoBtn');if(!b)return;
      b.dataset.enabled=String(Boolean(d.new_entries_enabled));
      b.textContent=d.new_entries_enabled?'AUTO ON':'AUTO OFF';
      b.classList.toggle('off',!d.new_entries_enabled);
    }catch(_){}
  }

  async function toggleAuto(){
    const b=q('#v34AutoBtn');if(!b)return;
    const next=b.dataset.enabled!=='true';b.disabled=true;
    try{
      const r=await fetch('/api/trading-control',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({new_entries_enabled:next})});
      if(!r.ok)throw new Error(r.status);await loadAuto();
    }catch(e){console.error(e)}finally{b.disabled=false}
  }

  function buildControlStrip(){
    const strip=q('.control-strip');if(!strip)return;
    q('#v33MasterControl')?.remove();
    qa('.control-strip > .control-stat').forEach(x=>x.remove());
    strip.classList.add('v34-control-strip');
    if(!q('#v34SearchBox')){
      const box=document.createElement('div');box.id='v34SearchBox';box.className='v34-search-box';
      box.innerHTML='<small>STOCK SEARCH</small><div class="v34-search-line"><input id="v34SearchInput" autocomplete="off" placeholder="종목명 / 종목코드 검색"><span>⌕</span></div><div id="v34SearchResults" class="v34-search-results"></div>';
      strip.appendChild(box);
      q('#v34SearchInput').addEventListener('input',e=>{
        clearTimeout(searchTimer);searchTimer=setTimeout(()=>searchStocks(e.target.value),180);
      });
      q('#v34SearchInput').addEventListener('focus',e=>{if(e.target.value.trim())searchStocks(e.target.value)});
      document.addEventListener('click',e=>{if(!e.target.closest('#v34SearchBox'))q('#v34SearchResults')?.classList.remove('open')});
    }
    if(!q('#v34FlowAlerts')){
      const box=document.createElement('div');box.id='v34FlowAlerts';box.className='v34-alert-slot';
      box.innerHTML='<div class="v34-alert-idle"><small>KR ABNORMAL FLOW</small><b>직전 5거래일 동시간대 이상수급 감시</b></div>';
      strip.appendChild(box);
    }
  }

  async function searchStocks(raw){
    const text=String(raw||'').trim(),result=q('#v34SearchResults');if(!result)return;
    if(!text){result.innerHTML='';result.classList.remove('open');return}
    const market=currentMarket();
    try{
      const r=await fetch(`/api/v34/search?market=${market}&q=${encodeURIComponent(text)}`,{cache:'no-store'});const d=await r.json();
      const rows=d.items||[];
      result.innerHTML=rows.length?rows.map(x=>{const px=Number(x.price||0),priceText=px>0?(x.market==='US'?'$'+px.toLocaleString(undefined,{maximumFractionDigits:4}):px.toLocaleString('ko-KR')+'원'):'클릭 시 최근가 조회';return `<button type="button" data-v34-stock="${esc(x.market)}/${esc(x.code)}"><span><b>${esc(x.name||x.code)}</b><small>${esc(x.code)} · ${esc(x.sector||'')}</small></span><em>${esc(priceText)}</em></button>`}).join(''):'<div class="v34-search-empty">검색 결과 없음</div>';
      result.classList.add('open');
      result.querySelectorAll('[data-v34-stock]').forEach(b=>b.addEventListener('click',async()=>{const key=b.dataset.v34Stock||'',parts=key.split('/'),m=parts[0],code=parts[1];b.disabled=true;try{await fetch(`/api/v34/track/${encodeURIComponent(m)}/${encodeURIComponent(code)}`,{method:'POST',cache:'no-store'})}catch(_){}location.href='/stock/'+key}));
    }catch(e){console.error(e)}
  }

  async function loadFlowAlerts(){
    const slot=q('#v34FlowAlerts');if(!slot)return;
    if(currentMarket()!=='KR'){
      slot.innerHTML='<div class="v34-alert-idle"><small>US MARKET</small><b>종목 검색 · SEC 공시 분석</b></div>';return;
    }
    try{
      const r=await fetch('/api/v34/flow-alerts',{cache:'no-store'});const d=await r.json(),rows=d.items||[];
      if(!rows.length){slot.innerHTML='<div class="v34-alert-idle"><small>KR ABNORMAL FLOW</small><b>직전 5거래일 동시간대 이상수급 감시</b></div>';return}
      slot.innerHTML='<div class="v34-alerts-wrap">'+rows.slice(0,3).map((x,i)=>{
        const f=x.flow||{},side=k=>f[k]?.side||'대기';
        return `<button class="v34-flow-alert" data-stock="KR/${esc(x.code)}"><div class="v34-flow-head"><span>${i+1}순위</span><b>${esc(x.name||x.code)}</b><em>${Number(x.priority_score||0).toFixed(0)}점</em></div><div class="v34-flow-core">거래량 ${Number(x.volume_ratio_5d_1m||0).toFixed(1)}× · 체결 ${Number(x.execution_strength||0).toFixed(0)} (${Number(x.execution_accel_60s||0)>=0?'+':''}${Number(x.execution_accel_60s||0).toFixed(1)}) · 5분 상승</div><div class="v34-flow-sides"><span>외 ${side('foreign')}</span><span>기관 ${side('institution')}</span><span>연기금 ${side('pension')}</span><span>프로그램 ${side('program')}</span></div></button>`;
      }).join('')+'</div>';
    }catch(e){console.error(e)}
  }

  function keepSignalsVisible(){
    const closed=q('#candidateClosed'),zone=q('#candidateZone'),smart=q('#smartSec');
    closed?.classList.add('hide');zone?.classList.remove('hide');
    if(currentMarket()==='KR')smart?.classList.remove('hide');else smart?.classList.add('hide');
    // Remove stale "장 종료" phrases without changing the actual market engine.
    qa('.flow-tile small,.sector-leader strong').forEach(el=>{if(el.textContent.trim()==='장 종료')el.textContent='분석 대기'});
  }

  async function loadCachedKr(){
    keepSignalsVisible();
    if(currentMarket()!=='KR')return;
    try{
      const r=await fetch('/api/v34/cached-candidates?market=KR&n=12',{cache:'no-store'});const d=await r.json();
      const smart=d.smart||[],scalp=d.scalp||[];
      if(typeof window.candidateCard==='function'){
        const smartList=q('#smartList');if(smartList&&smart.length)smartList.innerHTML=smart.map((x,i)=>window.candidateCard(x,true,i+1)).join('');
        const scalpList=q('#scalpList');if(scalpList&&scalp.length&&(!scalpList.children.length||scalpList.querySelector('.empty')))scalpList.innerHTML=scalp.map((x,i)=>window.candidateCard(x,false,i+1)).join('');
      }
    }catch(e){console.error(e)}
  }

  function eventSummary(e){
    if(e.blocked)return '중대 리스크 공시 · 신규진입 차단';
    if(e.sentiment==='positive')return '호재 +5점 · 진입 전 최근 5개 1분봉 상승추세 확인';
    if(e.sentiment==='negative')return '악재 -5점 · 진입점수에 감점';
    return '중립 0점 · 원문 확인';
  }

  async function loadUsEvents(){
    if(currentMarket()!=='US')return;
    try{
      const r=await fetch('/api/v34/events?market=US',{cache:'no-store'});const d=await r.json(),rows=d.items||[];
      const status=q('#eventStatus'),list=q('#eventList');
      if(status)status.textContent=d.status||'SEC EDGAR';
      if(list)list.innerHTML=rows.length?rows.map(e=>`<div class="event-item"><div class="event-head"><span class="event-label ${e.sentiment==='negative'?'negative':''}">${esc(e.label)} ${Number(e.score||0)?(Number(e.score)>0?'+':'')+Number(e.score).toFixed(0):''}</span><small>${esc(e.date||'')}</small></div><button class="event-stock-link" data-stock="US/${esc(e.code)}">${esc(e.corp_name||e.code)} ↗</button><b>${esc(e.title)}</b><div class="event-ai-summary"><strong>판정</strong><span>${esc(eventSummary(e))}</span></div><small>SEC EDGAR</small>${e.url?`<br><a href="${esc(e.url)}" target="_blank" rel="noopener">공시 원문 ↗</a>`:''}</div>`).join(''):'<div class="empty">최근 SEC 공시 없음 또는 수신 대기</div>';
    }catch(e){console.error(e)}
  }

  function updateSearchPlaceholder(){
    const i=q('#v34SearchInput');if(i)i.placeholder=currentMarket()==='US'?'미국 종목명 / 티커 검색':'국내 종목명 / 종목코드 검색';
  }

  async function enhanceCalendarDay(date){
    if(!date)return;
    const [y,m]=date.split('-').map(Number);
    try{
      const r=await fetch(`/api/pnl-calendar?scope=stock&year=${y}&month=${m}`,{cache:'no-store'});const d=await r.json(),row=d.days?.[date],box=q('#profitDetailList');
      if(!box)return;
      box.innerHTML=row?(row.trades||[]).map(t=>`<div class="profit-row v34-profit-row"><div><b>${esc(t.name||t.code)}</b> <span class="market-badge">${esc(t.market||'')}</span><br><small>${esc(t.date||date)} ${esc(t.time||'')} KST · ${Number(t.qty||0).toLocaleString()}주 · 매도 ${t.market==='US'?'$'+Number(t.price||0).toLocaleString(undefined,{maximumFractionDigits:4}):Number(t.price||0).toLocaleString('ko-KR')+'원'}</small></div><div><b class="${Number(t.pnl||0)>=0?'pos':'neg'}">${won(t.pnl)}</b><br><small>${pct(t.pnl_pct)}</small></div></div>`).join(''):'<div class="empty">실현 매매 없음</div>';
    }catch(e){console.error(e)}
  }

  function watchMode(){
    const obs=new MutationObserver(()=>{updateSearchPlaceholder();keepSignalsVisible();setTimeout(loadUsEvents,50)});
    ['#krModeLabel','#usModeLabel'].forEach(s=>{const el=q(s);if(el)obs.observe(el,{attributes:true,attributeFilter:['class']})});
  }

  function init(){
    addWithAlice();cleanHero();normalizeTop();buildControlStrip();updateSearchPlaceholder();keepSignalsVisible();watchMode();
    document.addEventListener('click',e=>{const d=e.target.closest?.('[data-date]');if(d)setTimeout(()=>enhanceCalendarDay(d.dataset.date),30)});
    loadFlowAlerts();loadCachedKr();loadUsEvents();
    setInterval(loadAuto,12000);setInterval(loadFlowAlerts,3000);setInterval(loadCachedKr,7000);setInterval(()=>{keepSignalsVisible();loadUsEvents()},4000);
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init);else init();
})();
