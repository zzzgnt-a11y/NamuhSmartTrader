(function(){
'use strict';

const $=s=>document.querySelector(s);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({
  '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'
}[c]));

let seq=0,aborter=null,timer=null,composing=false,homeAnchor=null;
const cache=new Map();

function market(){
  return $('#usModeLabel')?.classList.contains('active')?'US':'KR';
}

function rememberHome(box){
  if(homeAnchor||!box?.parentNode)return;
  homeAnchor=document.createComment('v348-search-home');
  box.parentNode.insertBefore(homeAnchor,box);
}

function placeSearchBox(){
  const box=$('#v34SearchBox');
  const strip=$('.control-strip');
  const budget=strip?.querySelector('.budget-control');
  if(!box||!strip||!budget)return;
  if(innerWidth<=780){
    if(box.nextElementSibling!==budget)strip.insertBefore(box,budget);
  }else if(homeAnchor?.parentNode){
    const next=homeAnchor.nextSibling;
    if(next!==box)homeAnchor.parentNode.insertBefore(box,next);
  }
}

function positionResults(){
  const box=$('#v34SearchBox');
  const input=$('#v34SearchInput');
  const r=$('#v34SearchResults');
  if(!box||!input||!r)return;

  // Always anchor the dropdown to the search card itself.  Do not use the
  // old fixed top:145px mobile rule or flip the panel above the input.
  r.style.setProperty('position','absolute','important');
  r.style.setProperty('left','12px','important');
  r.style.setProperty('right','12px','important');
  r.style.setProperty('top','calc(100% + 6px)','important');
  r.style.setProperty('bottom','auto','important');
  r.style.setProperty('z-index','12050','important');

  const vv=window.visualViewport;
  const rect=box.getBoundingClientRect();
  const bottom=(vv?.offsetTop||0)+(vv?.height||innerHeight);
  const available=Math.max(110,Math.floor(bottom-rect.bottom-18));
  r.style.setProperty('max-height',Math.min(360,available)+'px','important');
}

function close(){
  const r=$('#v34SearchResults');
  if(r){r.classList.remove('open');r.innerHTML='';}
  $('#v34SearchBox')?.classList.remove('v348-open');
}

function renderRows(rows){
  const r=$('#v34SearchResults');
  if(!r)return;
  if(!rows.length){
    r.innerHTML='<div class="v34-search-empty">검색 결과 없음</div>';
    positionResults();
    return;
  }
  r.innerHTML=rows.map(x=>{
    const px=Number(x.price||0);
    const price=px>0
      ?(x.market==='US'?'$'+px.toLocaleString(undefined,{maximumFractionDigits:4}):px.toLocaleString('ko-KR')+'원')
      :'선택하여 시세 연결';
    return `<button type="button" data-v348="${esc(x.market)}/${esc(x.code)}" data-name="${esc(x.name||x.code)}" data-sector="${esc(x.sector||'')}">
      <span><b>${esc(x.name||x.code)}</b><small>${esc(x.code)}${x.sector?' · '+esc(x.sector):''}</small></span>
      <em>${esc(price)}</em>
    </button>`;
  }).join('');

  r.querySelectorAll('[data-v348]').forEach(b=>{
    b.addEventListener('click',e=>{
      e.preventDefault();
      e.stopPropagation();
      openStock(b);
    });
  });
  positionResults();
}

async function run(raw){
  const input=$('#v34SearchInput');
  const r=$('#v34SearchResults');
  const text=String(raw||'').trim();
  if(!r)return;
  if(!text){
    if(aborter)aborter.abort();
    close();
    return;
  }

  const n=++seq,m=market(),key=m+'|'+text.toLowerCase();
  if(aborter)aborter.abort();
  r.classList.add('open');
  $('#v34SearchBox')?.classList.add('v348-open');
  positionResults();

  if(cache.has(key)){
    renderRows(cache.get(key));
    return;
  }

  r.innerHTML='<div class="v34-search-empty">검색 중…</div>';
  const controller=new AbortController();
  aborter=controller;
  const timeout=setTimeout(()=>controller.abort(),4500);
  try{
    const res=await fetch(`/api/v348/search?market=${m}&q=${encodeURIComponent(text)}`,{cache:'no-store',signal:controller.signal});
    if(!res.ok)throw new Error('HTTP '+res.status);
    const d=await res.json();
    if(n!==seq||String(input?.value||'').trim()!==text||market()!==m)return;
    const rows=Array.isArray(d.items)?d.items:[];
    cache.set(key,rows);
    if(cache.size>120)cache.delete(cache.keys().next().value);
    renderRows(rows);
  }catch(e){
    if(n!==seq)return;
    r.innerHTML=`<div class="v34-search-empty">${e?.name==='AbortError'?'검색 응답 지연':'검색 연결 오류'} · 다시 입력</div>`;
    positionResults();
  }finally{
    clearTimeout(timeout);
  }
}

function openStock(b){
  const [m,code]=String(b.dataset.v348||'').split('/');
  if(!m||!code)return;
  const u=`/api/v348/track/${encodeURIComponent(m)}/${encodeURIComponent(code)}`+
    `?name=${encodeURIComponent(b.dataset.name||'')}&sector=${encodeURIComponent(b.dataset.sector||'')}`;
  try{fetch(u,{method:'POST',cache:'no-store',keepalive:true}).catch(()=>{});}catch(_){}
  location.assign(`/stock/${encodeURIComponent(m)}/${encodeURIComponent(code)}`);
}

function replaceBox(){
  const old=$('#v34SearchBox');
  if(!old)return;
  rememberHome(old);
  const fresh=old.cloneNode(true);
  old.replaceWith(fresh);
  placeSearchBox();

  const input=$('#v34SearchInput');
  if(!input)return;
  const setPlaceholder=()=>input.placeholder=market()==='US'?'미국 종목명 / 티커 검색':'국내 종목명 / 종목코드 검색';
  setPlaceholder();

  input.addEventListener('compositionstart',()=>{composing=true;clearTimeout(timer);});
  input.addEventListener('compositionend',e=>{composing=false;clearTimeout(timer);timer=setTimeout(()=>run(e.target.value),30);});
  input.addEventListener('input',e=>{
    if(composing||e.isComposing)return;
    clearTimeout(timer);
    timer=setTimeout(()=>run(e.target.value),100);
  });
  input.addEventListener('focus',()=>{
    placeSearchBox();
    positionResults();
    if(input.value.trim())run(input.value);
  });
  input.addEventListener('keydown',e=>{
    if(e.key==='Escape'){close();input.blur();return;}
    if(e.key==='Enter'&&!e.isComposing){
      const first=$('#v34SearchResults [data-v348]');
      if(first){e.preventDefault();openStock(first);}
    }
  });

  document.addEventListener('click',e=>{
    if(!e.target.closest('#v34SearchBox'))close();
  });

  let raf=0;
  const reposition=()=>{
    if(raf)cancelAnimationFrame(raf);
    raf=requestAnimationFrame(()=>{raf=0;placeSearchBox();positionResults();});
  };
  window.visualViewport?.addEventListener('resize',reposition);
  window.visualViewport?.addEventListener('scroll',reposition);
  window.addEventListener('resize',reposition);

  const obs=new MutationObserver(()=>{
    setPlaceholder();
    cache.clear();
    close();
  });
  ['#krModeLabel','#usModeLabel'].forEach(s=>{const el=$(s);if(el)obs.observe(el,{attributes:true,attributeFilter:['class']});});
}

function init(){
  document.body.classList.remove('v346-ui');
  replaceBox();
  document.body.classList.add('v348-ready');
}

if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});
else init();
})();
