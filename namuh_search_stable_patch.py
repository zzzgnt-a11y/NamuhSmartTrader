from __future__ import annotations

import re
from pathlib import Path

_INSTALLED = False

STYLE = r'''
<style id="v368StableSearchStyle">
#v368MobileSearch{display:none}
@media(max-width:780px){
  #v34SearchBox{display:none!important}
  #v368MobileSearch{
    display:block!important;position:relative!important;z-index:15000!important;
    width:100%!important;box-sizing:border-box!important;margin:0 0 12px!important;
    padding:14px 16px!important;border:1px solid rgba(94,120,155,.16)!important;
    border-radius:18px!important;background:#f8fbff!important;color:#172337!important;
    box-shadow:0 10px 28px rgba(34,70,110,.08)!important;
    backdrop-filter:none!important;-webkit-backdrop-filter:none!important;
    animation:none!important;transition:none!important;isolation:isolate!important;
    transform:translateZ(0);-webkit-backface-visibility:hidden;
  }
  #v368MobileSearch>small{display:block;margin-bottom:7px;color:#7f8ea3;font-size:9px;font-weight:850;letter-spacing:1px}
  #v368MobileSearch .v368-line{height:46px;display:flex;align-items:center;gap:8px;padding:0 12px;border:1px solid #dbe4ef;border-radius:14px;background:#fff}
  #v368MobileSearch input{width:100%;min-width:0;border:0;outline:0;background:transparent;color:#172337;font:inherit;font-size:13px;-webkit-appearance:none;appearance:none}
  #v368MobileSearch .v368-icon{color:#8090a7;font-size:18px;line-height:1}
  #v368SearchResults{display:none;position:absolute!important;left:0!important;right:0!important;top:calc(100% + 6px)!important;z-index:15020!important;max-height:360px!important;overflow:auto!important;padding:7px!important;border:1px solid #dbe4ef!important;border-radius:15px!important;background:#fff!important;box-shadow:0 18px 42px rgba(28,52,84,.18)!important;animation:none!important;transition:none!important;backdrop-filter:none!important;-webkit-backdrop-filter:none!important;transform:translateZ(0);-webkit-overflow-scrolling:touch}
  #v368SearchResults.open{display:block!important}
  #v368SearchResults button{width:100%!important;min-height:56px!important;padding:9px 10px!important;border:0!important;border-radius:10px!important;background:#fff!important;color:#172337!important;box-shadow:none!important;display:flex!important;align-items:center!important;justify-content:space-between!important;gap:10px!important;text-align:left!important}
  #v368SearchResults button:active{background:#f1f6fc!important}
  #v368SearchResults button span{min-width:0}
  #v368SearchResults button b,#v368SearchResults button small{display:block}
  #v368SearchResults button b{font-size:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  #v368SearchResults button small{margin-top:3px;color:#8291a5;font-size:9px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  #v368SearchResults button em{font-style:normal;color:#66778f;font-size:10px;white-space:nowrap}
  #v368SearchResults .v368-empty{padding:18px;text-align:center;color:#8291a5;font-size:10px}
}
</style>
'''

BLOCK = r'''
<section id="v368MobileSearch" aria-label="종목 검색">
  <small>STOCK SEARCH</small>
  <div class="v368-line"><input id="v368SearchInput" autocomplete="off" autocapitalize="off" spellcheck="false" enterkeyhint="search" placeholder="국내 종목명 / 종목코드 검색"><span class="v368-icon">⌕</span></div>
  <div id="v368SearchResults"></div>
</section>
'''

SCRIPT = r'''
<script id="v368StableSearchScript">
(()=>{
'use strict';
const q=s=>document.querySelector(s);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[c]));
let timer=0,seq=0,abort=null,composing=false;
const market=()=>q('#usModeLabel')?.classList.contains('active')?'US':'KR';
const input=()=>q('#v368SearchInput'),results=()=>q('#v368SearchResults');
function close(){const r=results();if(r){r.classList.remove('open');r.innerHTML=''}}
function placeholder(){const i=input();if(i)i.placeholder=market()==='US'?'미국 종목명 / 티커 검색':'국내 종목명 / 종목코드 검색'}
async function openStock(btn){
  const [m,code]=String(btn.dataset.stock||'').split('/');if(!m||!code)return;
  const r=results();r?.querySelectorAll('button').forEach(x=>x.disabled=true);
  try{
    const tr=await fetch(`/api/v34/track/${encodeURIComponent(m)}/${encodeURIComponent(code)}`,{method:'POST',cache:'no-store'});
    if(!tr.ok)throw new Error(`track ${tr.status}`);
    const d=await tr.json();if(d?.ok===false)throw new Error(d.error||'track failed');
    location.href=`/stock/${encodeURIComponent(m)}/${encodeURIComponent(code)}`;
  }catch(e){
    console.error(e);r?.querySelectorAll('button').forEach(x=>x.disabled=false);
    if(r)r.insertAdjacentHTML('afterbegin','<div class="v368-empty">종목 연결 실패 · 다시 눌러주세요</div>');
  }
}
async function search(raw){
  const text=String(raw||'').trim(),r=results(),i=input();if(!r)return;
  if(!text){if(abort)abort.abort();close();return}
  const my=++seq,m=market();if(abort)abort.abort();abort=new AbortController();
  r.innerHTML='<div class="v368-empty">종목 마스터 검색 중…</div>';r.classList.add('open');
  try{
    const res=await fetch(`/api/v34/search?market=${m}&q=${encodeURIComponent(text)}`,{cache:'no-store',signal:abort.signal});
    if(!res.ok)throw new Error(`HTTP ${res.status}`);
    const d=await res.json();if(my!==seq||String(i?.value||'').trim()!==text||market()!==m)return;
    const rows=Array.isArray(d.items)?d.items:[];
    if(!rows.length){r.innerHTML=`<div class="v368-empty">${d.master_error?'종목 마스터 재연결 중 · 잠시 후 다시 검색':'검색 결과 없음'}</div>`;return}
    r.innerHTML=rows.map(x=>{const px=Number(x.price||0),pt=px>0?(x.market==='US'?'$'+px.toLocaleString(undefined,{maximumFractionDigits:4}):px.toLocaleString('ko-KR')+'원'):(x.tracked?'현재가 수신 대기':'선택 시 현재가 연결');return `<button type="button" data-stock="${esc(x.market)}/${esc(x.code)}"><span><b>${esc(x.name||x.code)}</b><small>${esc(x.code)} · ${esc(x.sector||'업종 미분류')}</small></span><em>${esc(pt)}</em></button>`}).join('');
    r.querySelectorAll('[data-stock]').forEach(b=>b.addEventListener('click',()=>openStock(b),{once:true}));
  }catch(e){if(e?.name==='AbortError')return;console.error(e);if(my===seq)r.innerHTML='<div class="v368-empty">검색 서버 연결 오류 · 다시 시도</div>'}
}
function init(){
  const i=input(),r=results();if(!i||!r)return;
  placeholder();
  i.addEventListener('compositionstart',()=>{composing=true;clearTimeout(timer)});
  i.addEventListener('compositionend',e=>{composing=false;clearTimeout(timer);timer=setTimeout(()=>search(e.target.value),60)});
  i.addEventListener('input',e=>{if(composing||e.isComposing)return;clearTimeout(timer);timer=setTimeout(()=>search(e.target.value),170)});
  i.addEventListener('focus',()=>{if(i.value.trim())search(i.value)});
  i.addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.isComposing){e.preventDefault();r.querySelector('[data-stock]')?.click()}});
  document.addEventListener('pointerdown',e=>{if(!e.target.closest('#v368MobileSearch'))close()},{passive:true});
  ['#krModeLabel','#usModeLabel'].forEach(sel=>q(sel)?.addEventListener('click',()=>{if(abort)abort.abort();seq++;i.value='';close();setTimeout(placeholder,0)}));
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});else init();
})();
</script>
'''


def apply(ns=None):
    global _INSTALLED
    if _INSTALLED:
        return True
    root = Path(__file__).resolve().parent
    p = root / 'static' / 'index.html'
    try:
        text = p.read_text(encoding='utf-8')
        text = re.sub(r'\s*<style id="v368StableSearchStyle">.*?</style>\s*', '\n', text, flags=re.S)
        text = re.sub(r'\s*<section id="v368MobileSearch".*?</section>\s*', '\n', text, flags=re.S)
        text = re.sub(r'\s*<script id="v368StableSearchScript">.*?</script>\s*', '\n', text, flags=re.S)
        text = text.replace('</head>', STYLE + '\n</head>')
        text = text.replace('<main class="page">', '<main class="page">\n' + BLOCK, 1)
        text = text.replace('</body>', SCRIPT + '\n</body>')
        p.write_text(text, encoding='utf-8')
    except Exception as exc:
        print('NAMUH STABLE SEARCH ERROR:', str(exc)[:220], flush=True)
        return False
    _INSTALLED = True
    print('NAMUH stable mobile search active: no reparent, no viewport listeners, old mobile search hidden', flush=True)
    return True
