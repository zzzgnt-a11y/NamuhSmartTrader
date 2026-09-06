(()=>{
'use strict';
function market(){return document.querySelector('#usModeLabel')?.classList.contains('active')?'US':'KR'}
function apply(){
  const m=market(),cap=document.querySelector('#scalpCaption');
  if(cap){
    const n=document.querySelectorAll('#scalpList .v352-ai-card').length;
    const ready=[...document.querySelectorAll('#scalpList .score-badge')].filter(x=>Number(x.textContent||0)>=72).length;
    cap.textContent=`전체 ${n}종목 · 1차 50 + 기술 30 + 보조 20 · 72점 이상 ${ready}종목`;
  }
  const map=window.NAMUH_ALL_SCORE_MAP;
  if(!map)return;
  document.querySelectorAll('#scalpList .v352-ai-card').forEach(card=>{
    const ds=String(card.dataset.stock||'');const code=ds.split('/').pop();const x=map.get(String(code||'').toUpperCase());if(!x)return;
    const c=x.score_components||{},metrics=card.querySelectorAll('.metric');if(!metrics.length)return;
    const last=metrics[metrics.length-1],s=last.querySelector('span'),b=last.querySelector('b');
    if(s)s.textContent='50/30/20';
    if(b)b.textContent=`${Number(c.stage50||0).toFixed(0)}/${Number(c.stage30||0).toFixed(0)}/${Number(c.stage20||0).toFixed(0)}`;
  });
}
setInterval(apply,500);document.addEventListener('DOMContentLoaded',apply,{once:true});setTimeout(apply,100);
})();
