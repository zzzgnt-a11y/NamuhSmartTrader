(function(){
  function enhance(tip){
    if(!tip||tip.querySelector('.v34-tooltip-close'))return;
    const b=document.createElement('button');b.type='button';b.className='v34-tooltip-close';b.textContent='×';b.setAttribute('aria-label','닫기');
    b.addEventListener('click',e=>{e.preventDefault();e.stopPropagation();tip.dataset.v34Closed='1';tip.classList.add('hide')});
    tip.prepend(b);
  }
  function scan(){document.querySelectorAll('.chart-tooltip').forEach(enhance)}
  document.addEventListener('pointerdown',e=>{if(e.target.closest?.('canvas'))document.querySelectorAll('.chart-tooltip[data-v34-closed="1"]').forEach(t=>{delete t.dataset.v34Closed})},true);
  const obs=new MutationObserver(scan);if(document.body)obs.observe(document.body,{childList:true,subtree:true});
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',scan);else scan();
})();
