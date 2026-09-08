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
  const sorted=cards.slice().sort((a,b)=>score(b)-score(a));
  busy=true;
  try{
    // Reorder only when necessary. Re-appending an already sorted list would
    // retrigger MutationObserver forever and waste the browser main thread.
    if(!sorted.every((el,i)=>el===cards[i]))sorted.forEach(el=>root.appendChild(el));
    sorted.forEach((el,i)=>{
      const hide=i>=5;if(el.hidden!==hide)el.hidden=hide;
      const title=el.querySelector('.candidate-name b');
      if(title){const name=String(title.textContent||'').replace(/^\s*\d+\.\s*/,'');const next=`${i+1}. ${name}`;if(title.textContent!==next)title.textContent=next;}
    });
    const first=sorted[0];
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
