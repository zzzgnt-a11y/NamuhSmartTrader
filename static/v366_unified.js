(()=>{
'use strict';
function placeSearch(){
  const box=document.getElementById('v34SearchBox');
  if(!box)return;
  const mobile=window.innerWidth<=780;
  if(mobile){
    const page=document.querySelector('main.page');
    const hero=document.getElementById('homeSec')||page?.firstElementChild;
    if(page&&hero&&box.parentNode!==page)page.insertBefore(box,hero);
    else if(page&&hero&&box.nextElementSibling!==hero)page.insertBefore(box,hero);
    box.classList.add('v366-mobile-search');
  }else{
    box.classList.remove('v366-mobile-search');
    const strip=document.querySelector('.control-strip');
    const budget=strip?.querySelector('.budget-control');
    if(strip&&box.parentNode!==strip)strip.insertBefore(box,budget||strip.firstChild);
  }
}
function later(){requestAnimationFrame(()=>requestAnimationFrame(placeSearch))}
function init(){
  placeSearch();
  setTimeout(placeSearch,80);
  setTimeout(placeSearch,350);
  window.addEventListener('resize',later,{passive:true});
  window.visualViewport?.addEventListener('resize',later,{passive:true});
  window.visualViewport?.addEventListener('scroll',later,{passive:true});
  document.addEventListener('focusin',e=>{if(e.target?.id==='v34SearchInput')setTimeout(placeSearch,0)},true);
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});else init();
})();
