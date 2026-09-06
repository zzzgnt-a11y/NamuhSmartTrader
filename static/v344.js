(function(){
  'use strict';
  const q=s=>document.querySelector(s),qa=s=>[...document.querySelectorAll(s)];
  const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[c]));
  let autoSwitch=false,lastMode='',eventPage=1,eventTotal=1,eventBusy=false;
  const manualKey='GY_MANUAL_MARKET_THIS_TAB';
  const mode=()=>String(document.body.dataset.market||'KR').toUpperCase()==='US'?'US':'KR';
  function manual(){try{return sessionStorage.getItem(manualKey)==='1'}catch(_){return false}}

  function setClosedState(s){
    const m=mode(),closed=q('#candidateClosed'),zone=q('#candidateZone');
    if(m==='KR'&&!s.kr_active){
      zone?.classList.add('hide');
      closed?.classList.remove('hide');
      if(closed){const strong=closed.querySelector('strong')||closed.querySelector('b');if(strong)strong.textContent='장 종료 · NXT 거래 종료';}
    }
  }

  async function syncSession(){
    try{
      const r=await fetch('/api/v344/session',{cache:'no-store'});if(!r.ok)return;const s=await r.json();
      setClosedState(s);
      const want=String(s.default_view||'KR').toUpperCase();
      if(!manual()&&(want==='KR'||want==='US')&&mode()!==want){
        const b=q(want==='US'?'#usModeLabel':'#krModeLabel');
        if(b){autoSwitch=true;b.click();setTimeout(()=>{autoSwitch=false;loadEvents(true)},120)}
      }
    }catch(_){}
  }

  function buildEventBrowser(){
    const panel=q('.event-panel'),base=q('#eventList');if(!panel||!base)return null;
    base.style.display='none';
    let box=q('#v344EventBrowser');if(box)return box;
    box=document.createElement('div');box.id='v344EventBrowser';box.className='v344-event-browser';
    box.innerHTML='<div class="v344-event-head"><div><small>OFFICIAL DISCLOSURES</small><b id="v344EventTitle">최근 3개월 전종목 공시</b></div><span id="v344EventStatus">불러오는 중</span></div><div id="v344EventList" class="v344-event-list"></div><button id="v344EventMore" type="button" class="v344-more">더 보기</button>';
    base.insertAdjacentElement('afterend',box);
    q('#v344EventMore')?.addEventListener('click',()=>loadEvents(false));
    return box;
  }

  function eventRow(e){
    const cls=e.blocked?'blocked':e.sentiment==='negative'?'negative':e.sentiment==='positive'?'positive':'';
    const score=Number(e.score||0);return `<article class="v344-event-row ${cls}" data-stock="${esc((e.market||mode())+'/'+(e.code||''))}"><div class="v344-event-meta"><span>${esc(e.label||e.form||'공시')}${score?` ${score>0?'+':''}${score.toFixed(0)}`:''}</span><small>${esc(e.date||'')}</small></div><b>${esc(e.corp_name||e.code||'-')}</b><p>${esc(e.title||'-')}</p><small>${esc(e.source||'공식 공시')}</small></article>`}

  async function loadEvents(reset=true){
    if(eventBusy)return;const box=buildEventBrowser();if(!box)return;const m=mode();
    if(reset||lastMode!==m){eventPage=1;eventTotal=1;lastMode=m;q('#v344EventList').innerHTML=''}else if(eventPage>=eventTotal)return;
    eventBusy=true;const page=reset?1:eventPage+1;q('#v344EventStatus').textContent=`${m} · 갱신 중`;
    try{
      const r=await fetch(`/api/v344/disclosures?market=${m}&months=3&page=${page}&page_size=50`,{cache:'no-store'});if(!r.ok)throw new Error(r.status);const d=await r.json();
      if(reset)q('#v344EventList').innerHTML='';
      const rows=d.items||[];q('#v344EventList').insertAdjacentHTML('beforeend',rows.map(eventRow).join('')||(reset?'<div class="empty">최근 3개월 공시 없음 또는 공식 데이터 연결 대기</div>':''));
      eventPage=Number(d.page||page);eventTotal=Number(d.total_page||1);
      q('#v344EventTitle').textContent=m==='KR'?'최근 3개월 전종목 공시':'최근 3개월 기업공시';
      q('#v344EventStatus').textContent=`${m} · ${Number(d.total_count??rows.length).toLocaleString()}건 · ${d.source||''}`;
      q('#v344EventMore').style.display=eventPage<eventTotal?'block':'none';
    }catch(e){q('#v344EventStatus').textContent='공식 공시 연결 대기';console.error(e)}finally{eventBusy=false}
  }

  function bind(){
    document.addEventListener('click',e=>{
      const marketBtn=e.target.closest?.('#krModeLabel,#usModeLabel');
      if(marketBtn&&!autoSwitch){try{sessionStorage.setItem(manualKey,'1')}catch(_){}setTimeout(()=>{lastMode='';loadEvents(true)},180)}
      const row=e.target.closest?.('.v344-event-row[data-stock]');if(row){location.href='/stock/'+row.dataset.stock}
    },true);
  }
  function init(){bind();buildEventBrowser();syncSession();loadEvents(true);setInterval(syncSession,30000);setInterval(()=>{if(eventPage===1)loadEvents(true)},60000)}
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init);else init();
})();
