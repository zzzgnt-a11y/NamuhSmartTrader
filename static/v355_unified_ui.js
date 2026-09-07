(()=>{
'use strict';
const $=s=>document.querySelector(s),esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot',"'":'&#039;'}[c]||c));
function market(){return $('#usModeLabel')?.classList.contains('active')?'US':'KR'}
function money(v,m){const n=Number(v||0);return m==='US'?'$'+n.toLocaleString(undefined,{maximumFractionDigits:4}):Math.round(n).toLocaleString('ko-KR')+'원'}
function apply(){
  const m=market(),map=window.NAMUH_ALL_SCORE_MAP;if(!map)return;
  const rows=[...map.values()].sort((a,b)=>Number(b.score||0)-Number(a.score||0)),ready=rows.filter(x=>Number(x.score||0)>=72).length;
  const title=$('#scalpTitle'),cap=$('#scalpCaption');
  if(title)title.textContent=m==='US'?'미장 단타 탐지 · 국장 동일 레시피':'국장 단타 탐지';
  if(cap)cap.textContent=`전체 ${rows.length}종목 · 레시피 80 + 기술 20 · 72점 이상 ${ready}종목`;
  if(m==='US'){
    const sub=$('#subtitle');if(sub)sub.textContent='NHPLUG 공식 데이터 · 국장과 동일한 레시피80 + 기술20 단타';
  }
  document.querySelectorAll('#scalpList .v352-ai-card').forEach(card=>{
    const code=String(card.dataset.stock||'').split('/').pop().toUpperCase(),x=map.get(code);if(!x)return;
    const c=x.score_components||{},box=card.querySelector('.metrics');if(!box)return;
    box.innerHTML=[
      ['현재가',money(x.price,m)],['일봉',`${Number(c.daily20||0).toFixed(0)}/20`],['거래량',`${Number(c.volume15||0).toFixed(0)}/15`],
      ['체결강도',`${Number(c.execution20||0).toFixed(0)}/20`],['프로그램',`${Number(c.program15||0).toFixed(0)}/15`],['기술',`${Number(c.technical20||x.technical_score||0).toFixed(0)}/20`]
    ].map(a=>`<div class="metric"><span>${esc(a[0])}</span><b>${esc(a[1])}</b></div>`).join('');
  });
}
setInterval(apply,400);document.addEventListener('DOMContentLoaded',apply,{once:true});setTimeout(apply,100);
})();
