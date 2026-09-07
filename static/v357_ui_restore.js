/* with Alice only; intentionally no extra hero description */
(()=>{
  const apply=()=>{
    const subtitle=document.getElementById('subtitle');
    if(subtitle){ subtitle.textContent='with Alice'; subtitle.style.display=''; }
  };
  document.addEventListener('DOMContentLoaded',()=>{
    apply();
    const subtitle=document.getElementById('subtitle');
    if(subtitle){
      new MutationObserver(()=>{ if(subtitle.textContent!=='with Alice') subtitle.textContent='with Alice'; })
        .observe(subtitle,{childList:true,subtree:true,characterData:true});
    }
  });
  apply();
})();
