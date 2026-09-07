(()=>{
'use strict';
const $=s=>document.querySelector(s);
let queued=false;
function matched(x){
  const exact=String(x?.condition_display||'').trim();
  if(exact==='복합조건'||/^조건[123]$/.test(exact))return exact;
  const labels=[];
  for(const raw of (Array.isArray(x?.condition_labels)?x.condition_labels:[])){
    const s=String(raw||'').trim();
    if(/^조건[123]$/.test(s)&&!labels.includes(s))labels.push(s);
  }
  if(!labels.length){
    if(x?.condition1?.gate)labels.push('조건1');
    if(x?.condition2?.gate||x?.condition2_gate_pass)labels.push('조건2');
    if(x?.condition3?.gate)labels.push('조건3');
  }
  return labels.length>1?'복합조건':labels[0]||'';
}
function apply(){
  queued=false;
  const map=window.NAMUH_ALL_SCORE_MAP;
  document.querySelectorAll('#scalpList .v352-ai-card').forEach(card=>{
    const code=String(card.dataset.stock||'').split('/').pop().toUpperCase();
    const x=map?.get(code);if(!x)return;
    const reason=card.querySelector('.reason-row');if(reason)reason.style.display='none';
    const box=card.querySelector('.metrics');if(!box)return;
    const label=matched(x);
    const next=label?`<span class="strategy123-chip on">${label}</span>`:`<span class="strategy123-chip">조건 충족 없음</span>`;
    box.classList.add('strategy123-box');
    if(box.innerHTML!==next)box.innerHTML=next;
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
  #scalpList .v352-ai-card .reason-row{display:none!important}`;
  document.head.appendChild(s);
}
function init(){
  style();apply();
  const scalp=$('#scalpList'),positions=$('#positions'),obs=new MutationObserver(schedule);
  if(scalp)obs.observe(scalp,{childList:true,subtree:false});
  if(positions)obs.observe(positions,{childList:true,subtree:true});
  $('#krModeLabel')?.addEventListener('click',schedule);
  $('#usModeLabel')?.addEventListener('click',schedule);
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});else init();
})();
