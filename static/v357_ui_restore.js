/* Final minimal UI restore: Alice + original KR section 3 title + legacy trade label */
(()=>{
  let queued=false;
  const apply=()=>{
    queued=false;
    const subtitle=document.getElementById('subtitle');
    if(subtitle){ subtitle.textContent='with Alice'; subtitle.style.display=''; }

    const krActive=document.getElementById('krModeLabel')?.classList.contains('active');
    if(krActive){
      const title=document.getElementById('scalpTitle');
      if(title && title.textContent!=='국장 단타 탐지') title.textContent='국장 단타 탐지';
    }

    document.querySelectorAll('#profitDetailList .profit-row small').forEach(el=>{
      const text=String(el.textContent||'');
      if(text.includes('SCALP')) el.textContent=text.replace(/SCALP/g,'조건1');
    });
  };
  const schedule=()=>{
    if(queued)return;
    queued=true;
    requestAnimationFrame(apply);
  };
  document.addEventListener('DOMContentLoaded',()=>{
    apply();
    new MutationObserver(schedule).observe(document.body,{childList:true,subtree:true,characterData:true});
  },{once:true});
  apply();
})();
