(()=>{
'use strict';
// Display-only ranking contract. No CSS, no new elements, no option moves.
// Internal scanners/trading keep their complete candidate sets; the screen only
// shows the five highest final AI scores.
let busy=false;
const score=el=>{const n=Number(String(el?.querySelector('.score-badge')?.textContent||'').replace(/[^0-9.\-]/g,''));return Number.isFinite(n)?n:-Infinity};
function rank(root){
  if(!root||busy)return;
  const cards=[...root.querySelectorAll(':scope > .candidate')];
  if(!cards.length)return;
  busy=true;
  try{
    cards.sort((a,b)=>score(b)-score(a));
    cards.forEach((el,i)=>{root.appendChild(el);el.hidden=i>=5;});
    const first=cards[0];
    if(root.id==='scalpList'&&first){
      const name=String(first.querySelector('.candidate-name b')?.textContent||'').replace(/^\s*\d+\.\s*/,''),s=score(first),top=document.getElementById('topScalp');
      if(top&&Number.isFinite(s))top.textContent=`${name} ${Math.round(s)}점`;
    }
    if(root.id==='coinCandidateList'&&first){
      const name=String(first.querySelector('.candidate-name b')?.textContent||'').replace(/^\s*\d+\.\s*/,''),code=String(first.dataset.coin||''),s=score(first);
      const a=document.getElementById('coinTopSignal'),b=document.getElementById('coinLeadingSignal');
      if(a&&Number.isFinite(s))a.textContent=`${code||name} ${Math.round(s)}점`;
      if(b&&Number.isFinite(s))b.textContent=`${name} · ${Math.round(s)}점`;
    }
  }finally{busy=false;}
}
function install(id){
  const root=document.getElementById(id);if(!root)return;
  rank(root);
  new MutationObserver(()=>{if(!busy)queueMicrotask(()=>rank(root))}).observe(root,{childList:true});
}
function init(){install('scalpList');install('coinCandidateList');}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});else init();
})();
