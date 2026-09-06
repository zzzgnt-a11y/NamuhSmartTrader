(function(){
'use strict';

const $=s=>document.querySelector(s);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({
  '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'
}[c]));

let seq=0, aborter=null, timer=null, composing=false;
let homeAnchor=null;

function market(){
  return $('#usModeLabel')?.classList.contains('active') ? 'US' : 'KR';
}

function rememberHome(box){
  if(homeAnchor || !box?.parentNode) return;
  homeAnchor=document.createComment('v348-search-home');
  box.parentNode.insertBefore(homeAnchor,box);
}

function placeSearchBox(){
  const box=$('#v34SearchBox');
  const strip=$('.control-strip');
  const budget=strip?.querySelector('.budget-control');
  if(!box || !strip || !budget) return;

  if(innerWidth<=780){
    if(box.nextElementSibling!==budget) strip.insertBefore(box,budget);
  }else if(homeAnchor?.parentNode){
    const next=homeAnchor.nextSibling;
    if(next!==box) homeAnchor.parentNode.insertBefore(box,next);
  }
}

function positionResults(){
  const r=$('#v34SearchResults');
  const input=$('#v34SearchInput');
  if(!r || !input) return;

  if(innerWidth>780){
    for(const p of ['position','left','right','top','bottom','max-height','z-index']){
      r.style.removeProperty(p);
    }
    return;
  }

  const vv=window.visualViewport;
  const viewTop=vv?.offsetTop||0;
  const viewH=vv?.height||innerHeight;
  const viewBottom=viewTop+viewH;
  const rect=input.getBoundingClientRect();

  r.style.position='fixed';
  r.style.left='10px';
  r.style.right='10px';
  r.style.bottom='auto';
  r.style.zIndex='12050';

  const gap=8;
  const minUsable=96;
  const maxPanel=360;
  const belowTop=Math.max(viewTop+gap,rect.bottom+gap);
  const belowSpace=Math.max(0,viewBottom-belowTop-10);
  const aboveBottom=Math.min(viewBottom-gap,rect.top-gap);
  const aboveSpace=Math.max(0,aboveBottom-(viewTop+gap));

  // Prefer below the input. When the keyboard compresses the visual viewport,
  // use whichever side has more room and never force a panel taller than it.
  const useBelow=belowSpace>=minUsable || belowSpace>=aboveSpace;
  if(useBelow){
    const h=Math.max(48,Math.min(maxPanel,Math.floor(belowSpace)));
    r.style.top=Math.round(belowTop)+'px';
    r.style.maxHeight=h+'px';
  }else{
    const h=Math.max(48,Math.min(maxPanel,Math.floor(aboveSpace)));
    const top=Math.max(viewTop+gap,aboveBottom-h);
    r.style.top=Math.round(top)+'px';
    r.style.maxHeight=h+'px';
  }
}

function close(){
  const r=$('#v34SearchResults');
  if(r){
    r.classList.remove('open');
    r.innerHTML='';
  }
  document.body.classList.remove('v348-search-open');
}

async function run(raw){
  const input=$('#v34SearchInput');
  const r=$('#v34SearchResults');
  const text=String(raw||'').trim();
  if(!r) return;

  if(!text){
    if(aborter) aborter.abort();
    close();
    return;
  }

  const n=++seq;
  const m=market();
  if(aborter) aborter.abort();
  aborter=new AbortController();

  r.classList.add('open');
  document.body.classList.add('v348-search-open');
  r.innerHTML='<div class="v34-search-empty">검색 중…</div>';
  positionResults();

  try{
    const res=await fetch(`/api/v348/search?market=${m}&q=${encodeURIComponent(text)}`,{
      cache:'no-store',
      signal:aborter.signal
    });
    if(!res.ok) throw new Error('HTTP '+res.status);

    const d=await res.json();
    if(n!==seq || String(input?.value||'').trim()!==text || market()!==m) return;

    const rows=d.items||[];
    if(!rows.length){
      r.innerHTML='<div class="v34-search-empty">검색 결과 없음</div>';
      positionResults();
      return;
    }

    r.innerHTML=rows.map(x=>{
      const px=Number(x.price||0);
      const price=px>0
        ? (x.market==='US'
            ? '$'+px.toLocaleString(undefined,{maximumFractionDigits:4})
            : px.toLocaleString('ko-KR')+'원')
        : '선택하여 시세 연결';

      return `<button type="button"
        data-v348="${esc(x.market)}/${esc(x.code)}"
        data-name="${esc(x.name||x.code)}"
        data-sector="${esc(x.sector||'')}">
        <span>
          <b>${esc(x.name||x.code)}</b>
          <small>${esc(x.code)}${x.sector?' · '+esc(x.sector):''}</small>
        </span>
        <em>${esc(price)}</em>
      </button>`;
    }).join('');

    r.querySelectorAll('[data-v348]').forEach(b=>{
      b.addEventListener('pointerdown',e=>{
        e.preventDefault();
        if(!b.disabled) openStock(b);
      });
    });
    positionResults();
  }catch(e){
    if(e?.name==='AbortError') return;
    if(n===seq){
      r.innerHTML='<div class="v34-search-empty">검색 연결 오류 · 다시 입력</div>';
      positionResults();
    }
  }
}

async function openStock(b){
  const [m,code]=String(b.dataset.v348||'').split('/');
  if(!m || !code) return;

  const r=$('#v34SearchResults');
  r?.querySelectorAll('button').forEach(x=>x.disabled=true);

  try{
    const u=`/api/v348/track/${encodeURIComponent(m)}/${encodeURIComponent(code)}`
      +`?name=${encodeURIComponent(b.dataset.name||'')}`
      +`&sector=${encodeURIComponent(b.dataset.sector||'')}`;

    const res=await fetch(u,{method:'POST',cache:'no-store'});
    if(!res.ok) throw new Error('track '+res.status);

    const d=await res.json();
    if(d.ok===false) throw new Error(d.error||'track failed');

    location.href=`/stock/${encodeURIComponent(m)}/${encodeURIComponent(code)}`;
  }catch(e){
    r?.querySelectorAll('button').forEach(x=>x.disabled=false);
    r?.querySelector('[data-v348-track-error]')?.remove();
    r?.insertAdjacentHTML(
      'afterbegin',
      '<div class="v34-search-empty" data-v348-track-error>종목 연결 실패 · 다시 눌러주세요</div>'
    );
  }
}

function replaceBox(){
  const old=$('#v34SearchBox');
  if(!old) return;

  rememberHome(old);

  const fresh=old.cloneNode(true);
  old.replaceWith(fresh);

  placeSearchBox();

  const input=$('#v34SearchInput');
  if(!input) return;

  input.placeholder=market()==='US'
    ? '미국 종목명 / 티커 검색'
    : '국내 종목명 / 종목코드 검색';

  input.addEventListener('compositionstart',()=>{
    composing=true;
    clearTimeout(timer);
  });

  input.addEventListener('compositionend',e=>{
    composing=false;
    clearTimeout(timer);
    timer=setTimeout(()=>run(e.target.value),40);
  });

  input.addEventListener('input',e=>{
    if(composing || e.isComposing) return;
    clearTimeout(timer);
    timer=setTimeout(()=>run(e.target.value),120);
  });

  input.addEventListener('focus',()=>{
    placeSearchBox();
    positionResults();
    if(input.value.trim()) run(input.value);
  });

  input.addEventListener('keydown',e=>{
    if(e.key==='Enter' && !e.isComposing){
      e.preventDefault();
      const first=$('#v34SearchResults [data-v348]');
      if(first && !first.disabled) openStock(first);
    }
  });

  document.addEventListener('pointerdown',e=>{
    if(!e.target.closest('#v34SearchBox')) close();
  });

  let viewportRaf=0;
  const onViewport=()=>{
    if(viewportRaf) cancelAnimationFrame(viewportRaf);
    viewportRaf=requestAnimationFrame(()=>{
      viewportRaf=0;
      placeSearchBox();
      positionResults();
    });
  };
  window.visualViewport?.addEventListener('resize',onViewport);
  window.visualViewport?.addEventListener('scroll',onViewport);
  window.addEventListener('resize',onViewport);

  const obs=new MutationObserver(()=>{
    input.placeholder=market()==='US'
      ? '미국 종목명 / 티커 검색'
      : '국내 종목명 / 종목코드 검색';
    close();
  });

  ['#krModeLabel','#usModeLabel'].forEach(s=>{
    const el=$(s);
    if(el) obs.observe(el,{attributes:true,attributeFilter:['class']});
  });
}

function init(){
  // v346.css is detail-page styling. v34.js adds this legacy main class,
  // so remove only that class after v34 initialization to keep the main
  // page on its existing light styles.css/v34/v344 design.
  document.body.classList.remove('v346-ui');
  replaceBox();
  document.body.classList.add('v348-ready');
}

if(document.readyState==='loading'){
  document.addEventListener('DOMContentLoaded',init,{once:true});
}else{
  init();
}
})();
