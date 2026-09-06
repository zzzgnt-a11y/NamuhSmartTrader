(function(){
  'use strict';
  const q=s=>document.querySelector(s);
  const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[c]));
  let autoSwitch=false,lastMode='',eventPage=1,eventTotal=1,eventBusy=false,lastSession=null;
  const manualKey='GY_MANUAL_MARKET_THIS_TAB';
  const mode=()=>String(document.body.dataset.market||'KR').toUpperCase()==='US'?'US':'KR';
  function manual(){try{return sessionStorage.getItem(manualKey)==='1'}catch(_){return false}}

  function aiSummary(e){
    const t=String(e?.title||'');
    if(e?.blocked)return '중대 리스크 공시입니다. 신규진입 차단 대상으로 분류하며 원문에서 발생 규모와 진행상태를 확인합니다.';
    if(e?.sentiment==='negative'){
      if(/유상증자|전환사채|신주인수권|교환사채/.test(t))return '자금조달·희석 가능성이 있는 공시입니다. 발행규모와 조건을 확인하고 단타점수에 -5점을 반영합니다.';
      return '단기 부정 재료로 분류했습니다. 실제 손익·재무·법적 영향 확인이 필요하며 단타점수에 -5점을 반영합니다.';
    }
    if(e?.sentiment==='positive'){
      if(/공급계약|단일판매|수주|계약/.test(t))return '수주·계약 관련 긍정 재료입니다. 계약금액·기간·최근 매출 대비 비중을 확인하고 단타점수에 +5점을 반영합니다.';
      return '긍정 재료로 분류했습니다. 실제 실적 반영 시점과 지속성을 확인하고 단타점수에 +5점을 반영합니다.';
    }
    return '중립 공시입니다. 제목만으로 방향성을 단정하지 않고 원문 내용을 확인합니다.';
  }

  function separateSmartMoney(){
    const smart=q('#smartSec'),scalp=q('#scalpSec');if(!smart||!scalp||q('#v345SmartMoneySec'))return;
    const sec=document.createElement('section');sec.id='v345SmartMoneySec';sec.className='section-shell v345-smart-shell';
    sec.innerHTML='<div class="section-head"><div><span class="section-index">SM</span><div><small>SMART MONEY</small><h2>국장 스마트머니 탐지</h2></div></div><b>외국인·기관 누적수급 · 종가조건</b></div><div id="v345SmartHost"></div>';
    scalp.insertAdjacentElement('afterend',sec);q('#v345SmartHost').appendChild(smart);
    const title=smart.querySelector('.column-title');if(title)title.remove();
  }
  function syncSmartVisibility(){const wrap=q('#v345SmartMoneySec');if(!wrap)return;const show=mode()==='KR'&&Boolean(lastSession?.kr_active);wrap.classList.toggle('hide',!show)}

  function setClosedState(s){
    lastSession=s;const m=mode(),closed=q('#candidateClosed'),zone=q('#candidateZone');
    if(m==='KR'&&!s.kr_active){zone?.classList.add('hide');closed?.classList.remove('hide');const strong=closed?.querySelector('strong')||closed?.querySelector('b');if(strong)strong.textContent='장 종료 · NXT 거래 종료'}
    syncSmartVisibility();
  }
  async function syncSession(){
    try{const r=await fetch('/api/v344/session',{cache:'no-store'});if(!r.ok)return;const s=await r.json();setClosedState(s);const want=String(s.default_view||'KR').toUpperCase();if(!manual()&&(want==='KR'||want==='US')&&mode()!==want){const b=q(want==='US'?'#usModeLabel':'#krModeLabel');if(b){autoSwitch=true;b.click();setTimeout(()=>{autoSwitch=false;lastMode='';loadEvents(true)},160)}}}catch(e){console.error(e)}
  }

  function buildEventBrowser(){
    const panel=q('.event-panel'),base=q('#eventList');if(!panel||!base)return null;base.style.display='none';let box=q('#v344EventBrowser');if(box)return box;
    box=document.createElement('div');box.id='v344EventBrowser';box.className='v344-event-browser';
    box.innerHTML='<div class="v344-event-head"><div><small>OFFICIAL DISCLOSURES</small><b id="v344EventTitle">최근 3개월 전종목 공시</b></div><span id="v344EventStatus">불러오는 중</span></div><div id="v344EventList" class="v344-event-list"></div><button id="v344EventMore" type="button" class="v344-more">더 보기</button>';
    base.insertAdjacentElement('afterend',box);q('#v344EventMore')?.addEventListener('click',()=>loadEvents(false));return box;
  }
  function eventRow(e){
    const cls=e.blocked?'blocked':e.sentiment==='negative'?'negative':e.sentiment==='positive'?'positive':'';
    const score=Number(e.score||0);return `<article class="v344-event-row ${cls}" data-stock="${esc((e.market||mode())+'/'+(e.code||''))}"><div class="v344-event-meta"><span>${esc(e.label||e.form||'공시')}${score?` ${score>0?'+':''}${score.toFixed(0)}`:''}</span><small>${esc(e.date||'')}</small></div><b>${esc(e.corp_name||e.code||'-')}</b><p class="v344-event-titleline">${esc(e.title||'-')}</p><div class="v344-ai"><strong>AI 요약</strong><span>${esc(aiSummary(e))}</span></div><small>${esc(e.source||'공식 공시')}</small></article>`;
  }
  async function loadEvents(reset=true){
    if(eventBusy)return;const box=buildEventBrowser();if(!box)return;const m=mode();if(reset||lastMode!==m){eventPage=1;eventTotal=1;lastMode=m;q('#v344EventList').innerHTML=''}else if(eventPage>=eventTotal)return;
    eventBusy=true;const page=reset?1:eventPage+1;q('#v344EventStatus').textContent=`${m} · 갱신 중`;
    try{const r=await fetch(`/api/v344/disclosures?market=${m}&months=3&page=${page}&page_size=50`,{cache:'no-store'});if(!r.ok)throw new Error(r.status);const d=await r.json();if(reset)q('#v344EventList').innerHTML='';const rows=d.items||[];if(!d.ok&&d.status)throw new Error(d.status);q('#v344EventList').insertAdjacentHTML('beforeend',rows.map(eventRow).join('')||(reset?`<div class="empty">${esc(d.status||'최근 3개월 공시 없음 또는 공식 데이터 연결 대기')}</div>`:''));eventPage=Number(d.page||page);eventTotal=Number(d.total_page||1);q('#v344EventTitle').textContent=m==='KR'?'최근 3개월 전종목 공시':'최근 3개월 기업공시';q('#v344EventStatus').textContent=`${m} · ${Number(d.total_count??rows.length).toLocaleString()}건 · ${d.source||''}`;q('#v344EventMore').style.display=eventPage<eventTotal?'block':'none'}catch(e){q('#v344EventStatus').textContent='공식 공시 연결 오류';if(reset)q('#v344EventList').innerHTML=`<div class="empty">${esc(e.message||'공시 연결 오류')}</div>`;console.error(e)}finally{eventBusy=false}
  }

  function bind(){document.addEventListener('click',e=>{const marketBtn=e.target.closest?.('#krModeLabel,#usModeLabel');if(marketBtn&&!autoSwitch){try{sessionStorage.setItem(manualKey,'1')}catch(_){}setTimeout(()=>{lastMode='';syncSmartVisibility();loadEvents(true)},180)}const row=e.target.closest?.('.v344-event-row[data-stock]');if(row){const key=row.dataset.stock||'';if(key.split('/')[1])location.href='/stock/'+key}},true)}
  function init(){separateSmartMoney();bind();buildEventBrowser();syncSession();loadEvents(true);setInterval(syncSession,5000);setInterval(()=>loadEvents(true),60000)}
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init);else init();
})();
