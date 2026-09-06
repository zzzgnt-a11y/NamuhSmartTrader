(function(){
  'use strict';
  const q=s=>document.querySelector(s), qa=s=>[...document.querySelectorAll(s)];
  const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[c]));
  const mode=()=>q('#usModeLabel')?.classList.contains('active')?'US':'KR';
  const signed=(n,d=0)=>{const v=Number(n||0);return `${v>=0?'+':''}${v.toLocaleString('ko-KR',{maximumFractionDigits:d})}`};
  const flowMoney=n=>{const v=Number(n||0),a=Math.abs(v);if(a>=1e12)return `${v>=0?'+':'-'}${(a/1e12).toFixed(2)}조`;if(a>=1e8)return `${v>=0?'+':'-'}${(a/1e8).toLocaleString('ko-KR',{maximumFractionDigits:0})}억`;return `${v>=0?'+':'-'}${Math.round(a).toLocaleString('ko-KR')}원`};
  const cache={flow:null,flowAt:0,btc:null,btcAt:0,commodities:null,commAt:0,earn:new Map(),events:new Map()};
  let eventPage=1,eventMarket='KR',eventLoading=false,eventTotalPage=1;
  let marketMutationTimer=null,calendarTimer=null;

  function stabilizeSignals(){
    const closed=q('#candidateClosed'),zone=q('#candidateZone'),smart=q('#smartSec');
    closed?.classList.add('hide');zone?.classList.remove('hide');
    zone?.classList.add('v343-signal-stable');
    if(mode()==='KR')smart?.classList.remove('hide');else smart?.classList.add('hide');
    qa('#scalpList,#smartList').forEach(list=>{
      if(!list.children.length){list.innerHTML='<div class="empty v343-signal-wait">후보 데이터 축적 중 · 영역은 고정 유지</div>'}
    });
  }

  function sparkSvg(series){
    const v=(series||[]).map(Number).filter(x=>Number.isFinite(x)&&x>0);if(v.length<2)return '<div class="source-note">24H 추이 수신 대기</div>';
    const w=200,h=48,min=Math.min(...v),max=Math.max(...v),span=max-min||1;
    const pts=v.map((x,i)=>`${i/(v.length-1)*w},${h-4-(x-min)/span*(h-8)}`).join(' ');
    return `<svg class="spark v343-btc-spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none"><line x1="0" y1="${h-4}" x2="${w}" y2="${h-4}"></line><polyline points="${pts}"></polyline></svg>`;
  }

  async function loadBitcoin(force=false){
    const now=Date.now();if(!force&&cache.btc&&now-cache.btcAt<12000)return cache.btc;
    try{const r=await fetch('/api/v343/bitcoin',{cache:'no-store'});if(!r.ok)throw new Error(r.status);cache.btc=await r.json();cache.btcAt=now}catch(_){}
    return cache.btc;
  }

  function ensureBitcoinCard(){
    const grid=q('#markets');if(!grid||!cache.btc?.ok)return;
    let card=q('#v343BitcoinCard');const d=cache.btc,ch=Number(d.change_pct||0);
    const html=`<span class="market-label">BITCOIN · 24H</span><strong>${Number(d.value||0).toLocaleString('ko-KR',{maximumFractionDigits:0})}</strong><div class="delta ${ch>=0?'pos':'neg'}">${ch>=0?'+':''}${ch.toFixed(2)}%</div>${sparkSvg(d.series)}<div class="source-note">Coinone · KRW-BTC · 24시간</div><div class="chart-hint">차트 ↗</div>`;
    if(!card){card=document.createElement('article');card.id='v343BitcoinCard';card.className='market-card v343-bitcoin-card';card.dataset.coin='BTC';grid.appendChild(card)}
    if(card.dataset.sig!==html){card.dataset.sig=html;card.innerHTML=html}
  }

  async function loadMarketFlow(force=false){
    const now=Date.now();if(!force&&cache.flow&&now-cache.flowAt<60000)return cache.flow;
    try{const r=await fetch('/api/v343/market-flow',{cache:'no-store'});if(!r.ok)throw new Error(r.status);cache.flow=await r.json();cache.flowAt=now}catch(_){}
    return cache.flow;
  }

  function marketKey(card){return String(card.dataset.index||'').split('/').pop().toLowerCase()}
  function flowBox(row,key){
    const latest=row?.latest||{},ok=row?.ok&&Object.keys(latest).length;
    if(!ok){return `<div class="v343-market-flow v343-market-flow-empty"><span class="v343-market-flow-note">${esc(row?.note||'투자자 수급 공식값 수신 대기')}</span></div>`}
    const unit=key==='kospi_night'?'계약':'금액';
    const f=unit==='계약'?`${signed(latest.foreign)}계약`:flowMoney(latest.foreign);
    const i=unit==='계약'?`${signed(latest.institution)}계약`:flowMoney(latest.institution);
    const p=unit==='계약'?`${signed(latest.person)}계약`:flowMoney(latest.person);
    return `<div class="v343-market-flow"><span>외국인<b class="${Number(latest.foreign)>=0?'pos':'neg'}">${esc(f)}</b></span><span>기관<b class="${Number(latest.institution)>=0?'pos':'neg'}">${esc(i)}</b></span><span>개인<b class="${Number(latest.person)>=0?'pos':'neg'}">${esc(p)}</b></span><span class="v343-market-flow-note">${esc(row.source||'공식 수급')} · ${esc(row.asof||'최근 확정')}</span></div>`;
  }

  function decorateMarketCards(){
    const items=cache.flow?.items||{};
    qa('#markets .market-card[data-index]').forEach(card=>{
      const key=marketKey(card);if(!['kospi','kosdaq','kospi_night'].includes(key))return;
      const old=card.querySelector('.v343-market-flow');if(old)old.remove();
      card.insertAdjacentHTML('beforeend',flowBox(items[key],key));
    });
    ensureBitcoinCard();
  }

  function buildEventBrowser(){
    const panel=q('.event-panel'),base=q('#eventList');if(!panel||!base)return null;
    base.classList.add('v343-base-hidden');
    let box=q('#v343EventBrowser');if(box)return box;
    box=document.createElement('div');box.id='v343EventBrowser';box.className='v343-event-browser';
    box.innerHTML='<div class="v343-event-tabs"><button class="active" type="button">최근 6개월 기업공시</button><span id="v343EventState" class="v343-event-state">불러오는 중</span></div><div id="v343EventList" class="v343-event-list"></div><button id="v343EventMore" class="v343-more" type="button">더 보기</button>';
    base.insertAdjacentElement('afterend',box);q('#v343EventMore')?.addEventListener('click',()=>loadEventPage(false));return box;
  }

  function eventRow(e){
    const m=e.market||eventMarket,cls=e.blocked?'blocked':e.sentiment==='negative'?'negative':e.sentiment==='positive'?'positive':'';
    return `<article class="v343-event-row ${cls}"><div class="head"><span>${esc(e.label||e.form||'공시')}</span><small>${esc(e.date||'')}</small></div><button class="company" type="button" data-stock="${esc(m)}/${esc(e.code||'')}">${esc(e.corp_name||e.code||'-')} ↗</button><b>${esc(e.title||'-')}</b><div class="foot"><small>${esc(e.source||'공식 공시')}</small>${e.url?`<a href="${esc(e.url)}" target="_blank" rel="noopener">원문 ↗</a>`:''}</div></article>`;
  }

  async function loadEventPage(reset=true){
    const box=buildEventBrowser();if(!box||eventLoading)return;
    const m=mode();if(reset||m!==eventMarket){eventMarket=m;eventPage=1;eventTotalPage=1;q('#v343EventList').innerHTML=''}else if(eventPage>=eventTotalPage)return;
    eventLoading=true;q('#v343EventState').textContent=`${eventMarket} · 6개월 공시 불러오는 중`;
    try{
      const page=reset?1:eventPage+1,key=`${eventMarket}:${page}`;let d=cache.events.get(key);
      if(!d){const r=await fetch(`/api/v343/disclosures?market=${eventMarket}&months=6&page=${page}&page_size=50`,{cache:'no-store'});if(!r.ok)throw new Error(r.status);d=await r.json();cache.events.set(key,d)}
      if(reset)q('#v343EventList').innerHTML='';q('#v343EventList').insertAdjacentHTML('beforeend',(d.items||[]).map(eventRow).join('')||'<div class="empty">최근 6개월 공시 없음 또는 공식 데이터 연결 대기</div>');
      eventPage=Number(d.page||page);eventTotalPage=Number(d.total_page||1);
      const scope=d.scope?` · ${d.scope}`:'';q('#v343EventState').textContent=`${eventMarket} · ${Number(d.total_count||0).toLocaleString()}건${scope}`;
      q('#v343EventMore').style.display=eventPage<eventTotalPage?'block':'none';
    }catch(e){q('#v343EventState').textContent='공시 데이터 연결 대기';console.error(e)}finally{eventLoading=false}
  }

  function calendarYM(){const t=q('#profitMonthTitle')?.textContent||'',m=t.match(/(\d{4})년\s*(\d{1,2})월/);return m?[Number(m[1]),Number(m[2])]:[new Date().getFullYear(),new Date().getMonth()+1]}
  async function loadEarnings(force=false){
    const [y,m]=calendarYM(),mk=mode(),key=`${mk}:${y}-${m}`;
    if(!force&&cache.earn.has(key)){applyEarnings(cache.earn.get(key));return}
    try{const r=await fetch(`/api/v343/earnings?market=${mk}&year=${y}&month=${m}`,{cache:'no-store'});if(!r.ok)throw new Error(r.status);const d=await r.json();if(!d.refreshing)cache.earn.set(key,d);applyEarnings(d);if(d.refreshing)setTimeout(()=>loadEarnings(true),2500)}catch(e){console.error(e)}
  }

  function byDate(items){const out={};(items||[]).forEach(x=>(out[x.date]||(out[x.date]=[])).push(x));return out}
  function applyEarnings(data){
    const map=byDate(data?.items||[]);qa('#profitCalendar .day-cell[data-date]').forEach(cell=>{
      cell.querySelectorAll('.v343-earn-chip').forEach(x=>x.remove());const rows=map[cell.dataset.date]||[],stack=cell.querySelector('.macro-stack');if(!stack||!rows.length)return;
      rows.slice(0,2).forEach(x=>stack.insertAdjacentHTML('beforeend',`<span class="macro-chip earnings v343-earn-chip" title="${esc(x.name)}">실적 ${esc((x.name||x.code||'').slice(0,7))}</span>`));
      if(rows.length>2)stack.insertAdjacentHTML('beforeend',`<span class="macro-chip earnings v343-earn-chip">+${rows.length-2}</span>`);
    });
    const active=q('#profitCalendar .day-cell.active')?.dataset.date;if(active)renderEarningsDetail(active,data);
  }
  function renderEarningsDetail(date,data=null){
    const [y,m]=calendarYM(),key=`${mode()}:${y}-${m}`,d=data||cache.earn.get(key),rows=(d?.items||[]).filter(x=>x.date===date),host=q('#macroDetailList');if(!host)return;
    host.querySelector('.v343-earnings-detail')?.remove();if(!rows.length)return;
    const box=document.createElement('div');box.className='v343-earnings-detail';box.innerHTML=`<div class="v343-earn-title"><span class="tag earnings">EARNINGS</span><b>${date} 기업 실적공시 ${rows.length}건</b></div>`+rows.map(x=>`<div class="v343-earn-row"><b>${esc(x.name||x.code)} · ${esc(x.code||'')}</b><small>${esc(x.title||'실적공시')} · ${esc(x.source||'공식')}</small>${x.url?`<a href="${esc(x.url)}" target="_blank" rel="noopener"> 원문 ↗</a>`:''}</div>`).join('');host.appendChild(box);
  }

  function buildCommodityStrip(){const sec=q('#scalpSec');if(!sec)return null;let box=q('#v343CommodityStrip');if(box)return box;box=document.createElement('div');box.id='v343CommodityStrip';box.className='v343-commodity-strip';const head=sec.querySelector('.section-head');head?.insertAdjacentElement('afterend',box);return box}
  async function loadCommodities(force=false){
    const now=Date.now();if(!force&&cache.commodities&&now-cache.commAt<55000){renderCommodities();return}
    try{const r=await fetch('/api/v343/commodities',{cache:'no-store'});if(!r.ok)throw new Error(r.status);cache.commodities=await r.json();cache.commAt=now;renderCommodities()}catch(_){}
  }
  function renderCommodities(){const box=buildCommodityStrip();if(!box)return;const rows=cache.commodities?.items||[];if(!rows.length){box.innerHTML='<span class="v343-comm-status">원자재 보조점수 · NH 데이터 수신 대기</span>';return}box.innerHTML='<span class="v343-comm-title">COMMODITY ±5</span>'+rows.slice(0,8).map(x=>`<span class="v343-comm-chip"><b>${esc(x.label)}</b><em class="${Number(x.change_pct)>=0?'pos':'neg'}">${Number(x.change_pct)>=0?'+':''}${Number(x.change_pct||0).toFixed(2)}%</em></span>`).join('')}

  async function refreshDecorations(){
    stabilizeSignals();await Promise.all([loadMarketFlow(),loadBitcoin()]);decorateMarketCards();buildEventBrowser();loadCommodities();
  }

  function bind(){
    ['krModeLabel','usModeLabel'].forEach(id=>q('#'+id)?.addEventListener('click',()=>setTimeout(()=>{stabilizeSignals();loadEventPage(true);loadEarnings(true);loadMarketFlow(true).then(decorateMarketCards);loadBitcoin(true).then(ensureBitcoinCard)},250)));
    q('#profitSec')?.addEventListener('click',e=>{const day=e.target.closest?.('.day-cell[data-date]');if(day)setTimeout(()=>renderEarningsDetail(day.dataset.date),80);if(e.target.closest?.('#prevMonthBtn,#nextMonthBtn'))setTimeout(()=>loadEarnings(true),120)});
    const markets=q('#markets');if(markets)new MutationObserver(()=>{clearTimeout(marketMutationTimer);marketMutationTimer=setTimeout(()=>{decorateMarketCards();ensureBitcoinCard()},40)}).observe(markets,{childList:true});
    const cal=q('#profitCalendar');if(cal)new MutationObserver(()=>{clearTimeout(calendarTimer);calendarTimer=setTimeout(()=>loadEarnings(false),70)}).observe(cal,{childList:true});
    const zone=q('#candidateZone');if(zone)new MutationObserver(()=>stabilizeSignals()).observe(zone,{attributes:true,attributeFilter:['class']});
  }

  function init(){
    bind();refreshDecorations();loadEventPage(true);setTimeout(()=>loadEarnings(true),350);
    setInterval(()=>{stabilizeSignals();loadMarketFlow().then(decorateMarketCards);loadBitcoin().then(ensureBitcoinCard)},15000);
    setInterval(()=>loadCommodities(),60000);
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init);else init();
})();
