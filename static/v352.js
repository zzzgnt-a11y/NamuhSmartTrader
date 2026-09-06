(()=>{
'use strict';
const $=s=>document.querySelector(s);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[c]));
const stores={KR:{catalog:null,scores:[],map:new Map(),updated:0},US:{catalog:null,scores:[],map:new Map(),updated:0}};
let searchTimer=0,searchInstalled=false,rendering=false,lastRenderKey='',loadSeq=0;

function market(){return $('#usModeLabel')?.classList.contains('active')?'US':'KR'}
function money(v,m){const n=Number(v||0);if(!n)return '—';return m==='US'?'$'+n.toLocaleString(undefined,{maximumFractionDigits:4}):Math.round(n).toLocaleString('ko-KR')+'원'}
function nrm(s){return String(s||'').toLowerCase().replace(/\s+/g,'')}
function scoreText(v){return v!==null&&v!==undefined&&v!==''&&Number.isFinite(Number(v))?'AI '+Number(v).toFixed(0)+'점':'AI 수신대기'}

async function loadUniverse(forceCatalog=false){
  const m=market(),st=stores[m],want=forceCatalog||!st.catalog,n=++loadSeq;
  try{
    const r=await fetch(`/api/v352/universe?market=${m}&catalog=${want?1:0}`,{cache:'no-store'});
    if(!r.ok)throw new Error('universe '+r.status);
    const d=await r.json();
    if(m!==market()||n<loadSeq-2)return;
    st.scores=Array.isArray(d.scores)?d.scores:[];
    st.map=new Map(st.scores.map(x=>[String(x.code||'').toUpperCase(),x]));
    st.updated=Number(d.updated_at||0);
    if(Array.isArray(d.catalog))st.catalog=d.catalog;
    window.NAMUH_ALL_SCORE_MAP=st.map;
    renderAllScores();annotateSector();
    if(searchInstalled)renderSearch($('#v34SearchInput')?.value||'');
  }catch(e){console.error('v352 universe',e)}
}

function allCard(x,i,m){
  const comp=x.score_components||{},recipe=x.recipe_score,ds=x.daily_score,ms=x.minute_score,ex=x.execution_strength;
  const details=m==='KR'
    ?[['현재가',money(x.price,m)],['체결강도',ex==null?'—':Number(ex).toFixed(1)],['일봉',ds==null?'—':Number(ds).toFixed(0)],['분봉',ms==null?'—':Number(ms).toFixed(0)],['레시피',recipe==null?'—':Number(recipe).toFixed(0)]]
    :[['현재가',money(x.price,m)],['일봉',ds==null?'—':Number(ds).toFixed(0)],['분봉',ms==null?'—':Number(ms).toFixed(0)],['레시피',recipe==null?'—':Number(recipe).toFixed(0)],['40/60',`${Number(comp.context40||0).toFixed(0)}/${Number(comp.technical60||0).toFixed(0)}`]];
  return `<article class="candidate v352-ai-card" data-stock="${esc(m)}/${esc(x.code)}"><div class="candidate-top"><div class="candidate-name"><b>${i+1}. ${esc(x.name||x.code)}</b><small>${esc(x.code)} · ${esc(x.sector||'')}</small></div><div class="score-badge">${Number(x.score||0).toFixed(0)}</div></div><div class="reason-row">${(x.reasons||[]).slice(0,4).map(r=>`<span class="pill">${esc(r)}</span>`).join('')}</div><div class="metrics">${details.map(a=>`<div class="metric"><span>${esc(a[0])}</span><b>${esc(a[1])}</b></div>`).join('')}</div></article>`
}

function renderAllScores(){
  const list=$('#scalpList'),m=market(),st=stores[m];if(!list||!st.scores.length)return;
  const rows=st.scores.slice().sort((a,b)=>Number(b.score||0)-Number(a.score||0));
  const key=m+'|'+rows.map(x=>`${x.code}:${Number(x.score||0).toFixed(1)}:${Number(x.price||0)}`).join(',');
  const ready=rows.filter(x=>Number(x.score||0)>=72).length,title=$('#scalpTitle'),cap=$('#scalpCaption');
  if(title)title.textContent=m==='US'?'미장 전체 종목 AI 점수':'국장 전체 종목 AI 점수';
  if(cap)cap.textContent=`전체 ${rows.length}종목 · 40 실시간 + 60 일봉→분봉 · 72점 이상 ${ready}종목`;
  const col=list.closest('.signal-column')?.querySelector('.column-title b');if(col)col.textContent=`전체 AI 점수 · ${rows.length}종목`;
  $('#candidateClosed')?.classList.add('hide');$('#candidateZone')?.classList.remove('hide');
  if(key===lastRenderKey&&list.dataset.v352==='1'&&list.querySelector('.v352-ai-card'))return;
  rendering=true;lastRenderKey=key;list.innerHTML=rows.map((x,i)=>allCard(x,i,m)).join('');list.dataset.v352='1';rendering=false;
}

function rankCatalog(rows,q){
  const z=nrm(q);if(!z)return [];
  return (rows||[]).map(x=>{
    const code=nrm(x.code),name=nrm(x.name);let rank=99;
    if(code===z||name===z)rank=0;else if(code.startsWith(z))rank=1;else if(name.startsWith(z))rank=2;else if(code.includes(z))rank=3;else if(name.includes(z))rank=4;else return null;
    const live=stores[market()].map.get(String(x.code||'').toUpperCase());return {...x,score:live?live.score:x.score,_rank:rank};
  }).filter(Boolean).sort((a,b)=>a._rank-b._rank||Number(b.score??-1)-Number(a.score??-1)||String(a.name).localeCompare(String(b.name),'ko')).slice(0,14)
}

function positionResults(){
  const box=$('#v34SearchBox'),r=$('#v34SearchResults');if(!box||!r)return;
  r.style.setProperty('position','absolute','important');
  r.style.setProperty('left','12px','important');
  r.style.setProperty('right','12px','important');
  r.style.setProperty('top','calc(100% + 6px)','important');
  r.style.setProperty('bottom','auto','important');
  r.style.setProperty('z-index','12050','important');
  const vv=window.visualViewport,rect=box.getBoundingClientRect(),bottom=(vv?.offsetTop||0)+(vv?.height||innerHeight),available=Math.max(110,Math.floor(bottom-rect.bottom-18));
  r.style.setProperty('max-height',Math.min(360,available)+'px','important');
}
function closeSearch(){const r=$('#v34SearchResults');if(r){r.classList.remove('open');r.innerHTML=''}$('#v34SearchBox')?.classList.remove('v348-open')}
function renderSearch(raw){
  const r=$('#v34SearchResults'),input=$('#v34SearchInput'),q=String(raw||'').trim(),m=market(),st=stores[m];if(!r||!input)return;
  if(!q){closeSearch();return}
  r.classList.add('open');$('#v34SearchBox')?.classList.add('v348-open');positionResults();
  if(!st.catalog){r.innerHTML='<div class="v34-search-empty">종목목록 준비 중…</div>';loadUniverse(true);return}
  const rows=rankCatalog(st.catalog,q);if(!rows.length){r.innerHTML='<div class="v34-search-empty">검색 결과 없음</div>';return}
  r.innerHTML=rows.map(x=>{
    const score=scoreText(x.score),px=money(x.price,x.market);
    return `<button type="button" data-v352-stock="${esc(x.market)}/${esc(x.code)}" data-name="${esc(x.name||x.code)}" data-sector="${esc(x.sector||'')}"><span><b>${esc(x.name||x.code)}</b><small>${esc(x.code)}${x.sector?' · '+esc(x.sector):''}</small></span><em><strong class="v352-search-score">${esc(score)}</strong><small>${esc(px)}</small></em></button>`
  }).join('');
  r.querySelectorAll('[data-v352-stock]').forEach(b=>b.addEventListener('click',e=>{e.preventDefault();e.stopPropagation();openStock(b)}));positionResults();
}
function openStock(b){
  const [m,code]=String(b.dataset.v352Stock||'').split('/');if(!m||!code)return;
  const u=`/api/v348/track/${encodeURIComponent(m)}/${encodeURIComponent(code)}?name=${encodeURIComponent(b.dataset.name||'')}&sector=${encodeURIComponent(b.dataset.sector||'')}`;
  try{fetch(u,{method:'POST',cache:'no-store',keepalive:true}).catch(()=>{})}catch(_){}
  location.assign(`/stock/${encodeURIComponent(m)}/${encodeURIComponent(code)}`)
}
function installSearch(){
  const old=$('#v34SearchBox');if(!old||old.dataset.v352==='1')return Boolean(old);
  const fresh=old.cloneNode(true);fresh.dataset.v352='1';old.replaceWith(fresh);const input=$('#v34SearchInput');if(!input)return false;searchInstalled=true;
  input.placeholder=market()==='US'?'미국 종목명 / 티커 즉시검색':'국내 종목명 / 종목코드 즉시검색';
  input.addEventListener('compositionstart',()=>clearTimeout(searchTimer));
  input.addEventListener('compositionend',e=>{clearTimeout(searchTimer);renderSearch(e.target.value)});
  input.addEventListener('input',e=>{if(e.isComposing)return;clearTimeout(searchTimer);searchTimer=setTimeout(()=>renderSearch(e.target.value),20)});
  input.addEventListener('focus',()=>{if(!stores[market()].catalog)loadUniverse(true);if(input.value.trim())renderSearch(input.value)});
  input.addEventListener('keydown',e=>{if(e.key==='Escape'){closeSearch();input.blur();return}if(e.key==='Enter'&&!e.isComposing){const first=$('#v34SearchResults [data-v352-stock]');if(first){e.preventDefault();first.click()}}});
  document.addEventListener('click',e=>{if(!e.target.closest('#v34SearchBox'))closeSearch()});
  window.visualViewport?.addEventListener('resize',positionResults);window.visualViewport?.addEventListener('scroll',positionResults);window.addEventListener('resize',positionResults);loadUniverse(true);return true;
}

function annotateSector(){
  const box=$('#sectorMemberList'),m=market(),map=stores[m].map;if(!box)return;
  box.querySelectorAll('.sector-member').forEach(row=>{
    if(row.querySelector('.v352-score-pill'))return;let code='';const ds=row.dataset.stock||'';if(ds.includes('/'))code=ds.split('/').pop();
    if(!code){const mm=row.textContent.match(m==='KR'?/\b\d{6}\b/:/\b[A-Z]{1,6}\b/);code=mm?.[0]||''}
    const x=map.get(String(code).toUpperCase()),pill=document.createElement('span');pill.className='v352-score-pill';pill.textContent=x?`AI ${Number(x.score||0).toFixed(0)}`:'AI 수신대기';row.appendChild(pill)
  })
}

function installStyle(){
  if($('#v352Style'))return;const s=document.createElement('style');s.id='v352Style';s.textContent=`
  #v34SearchBox{position:relative!important;overflow:visible!important;z-index:40}
  #v34SearchBox.v348-open{z-index:12040!important}
  #v34SearchResults{position:absolute!important;left:12px!important;right:12px!important;top:calc(100% + 6px)!important;bottom:auto!important;z-index:12050!important}
  .v352-search-score{display:block;font-size:12px;line-height:1.2}.v34-search-results button em small{display:block;font-size:10px;opacity:.72;margin-top:2px}
  .v352-score-pill{margin-left:auto;flex:0 0 auto;border:1px solid rgba(80,126,255,.22);border-radius:999px;padding:4px 7px;font-size:11px;font-weight:800;color:#4769bd;background:rgba(80,126,255,.07)}
  .v352-ai-card .score-badge{min-width:46px}#scalpList[data-v352="1"]{max-height:900px;overflow:auto;padding-right:3px}`;document.head.appendChild(s)
}

function init(){
  installStyle();let tries=0;const t=setInterval(()=>{tries++;if(installSearch()||tries>40)clearInterval(t)},100);
  const list=$('#scalpList');if(list)new MutationObserver(()=>{if(rendering)return;const st=stores[market()];if(st.scores.length&&!list.querySelector('.v352-ai-card')){lastRenderKey='';queueMicrotask(renderAllScores)}}).observe(list,{childList:true,subtree:false});
  const sec=$('#sectorMemberList');if(sec)new MutationObserver(()=>queueMicrotask(annotateSector)).observe(sec,{childList:true,subtree:true});
  ['#krModeLabel','#usModeLabel'].forEach(sel=>$(sel)?.addEventListener('click',()=>setTimeout(()=>{lastRenderKey='';loadUniverse(!stores[market()].catalog)},80)));
  loadUniverse(true);setInterval(()=>loadUniverse(false),8000);setInterval(()=>{renderAllScores();if(!$('#v34SearchBox')?.dataset.v352)installSearch()},1000)
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});else init();
})();
