(()=>{
'use strict';
const $=s=>document.querySelector(s);
function market(){return $('#usModeLabel')?.classList.contains('active')?'US':'KR'}
let queued=false;
function apply(){
  queued=false;
  const m=market(),title=$('#scalpTitle'),sub=$('#subtitle');
  const wanted=m==='US'?'미장 단타 탐지':'국장 단타 탐지';
  if(title&&title.textContent!==wanted)title.textContent=wanted;
  if(sub&&sub.textContent!=='with Alice')sub.textContent='with Alice';
}
function schedule(){if(queued)return;queued=true;requestAnimationFrame(apply)}
function init(){
  apply();
  const obs=new MutationObserver(schedule);
  const title=$('#scalpTitle'),sub=$('#subtitle');
  if(title)obs.observe(title,{childList:true,subtree:true,characterData:true});
  if(sub)obs.observe(sub,{childList:true,subtree:true,characterData:true});
  $('#krModeLabel')?.addEventListener('click',schedule);
  $('#usModeLabel')?.addEventListener('click',schedule);
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});else init();
})();
