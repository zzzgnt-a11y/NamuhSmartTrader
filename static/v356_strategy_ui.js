(()=>{
'use strict';
const $=s=>document.querySelector(s);
function market(){return $('#usModeLabel')?.classList.contains('active')?'US':'KR'}
let queued=false;
function apply(){
  queued=false;
  if(market()!=='KR')return;
  const map=window.NAMUH_ALL_SCORE_MAP;
  document.querySelectorAll('#scalpList .v352-ai-card').forEach(card=>{
    const code=String(card.dataset.stock||'').split('/').pop().toUpperCase();
    const x=map?.get(code);if(!x)return;
    const reason=card.querySelector('.reason-row');if(reason)reason.style.display='none';
    const box=card.querySelector('.metrics');if(!box)return;
    const c1=x.condition1||{},c2=x.condition2||{},c3=x.condition3||{};
    const next=[
      `<span class="strategy123-chip ${c1.gate?'on':''}">조건1 ${Number(c1.score??x.score??0).toFixed(0)}${c1.gate?' ✓':''}</span>`,
      `<span class="strategy123-chip ${c2.gate?'on':''}">조건2 ${Number(c2.score??x.condition2_score??0).toFixed(0)}${c2.gate?' ✓':''}</span>`,
      `<span class="strategy123-chip ${c3.sector_top3?'watch':''}">조건3 ${c3.sector_top3?'주도섹터 '+Number(c3.sector_rank||0)+'위':'감시대기'}</span>`
    ].join('');
    box.classList.add('strategy123-box');if(box.innerHTML!==next)box.innerHTML=next;
  });
  document.querySelectorAll('#positions .strategy-tag').forEach(t=>{if(t.textContent.trim()==='SCALP')t.textContent='조건1'});
}
function schedule(){if(queued)return;queued=true;requestAnimationFrame(apply)}
function style(){
  if($('#strategy123Style'))return;
  const s=document.createElement('style');s.id='strategy123Style';s.textContent=`
  .strategy123-box{display:flex!important;gap:6px!important;flex-wrap:wrap!important}
  .strategy123-chip{display:inline-flex;align-items:center;border:1px solid rgba(80,105,160,.18);border-radius:999px;padding:7px 10px;font-size:12px;font-weight:800;background:rgba(90,105,145,.06)}
  .strategy123-chip.on{border-color:rgba(35,145,95,.28);background:rgba(35,145,95,.10)}
  .strategy123-chip.watch{border-color:rgba(70,105,210,.28);background:rgba(70,105,210,.09)}
  #scalpList .v352-ai-card .reason-row{display:none!important}
  `;document.head.appendChild(s)
}
function init(){
  style();apply();
  const opts={childList:true,subtree:true};
  const scalp=$('#scalpList'),positions=$('#positions');
  if(scalp)new MutationObserver(schedule).observe(scalp,opts);
  if(positions)new MutationObserver(schedule).observe(positions,opts);
  setInterval(schedule,2000);
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});else init();
})();