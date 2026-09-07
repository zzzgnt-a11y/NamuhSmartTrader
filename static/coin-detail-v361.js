(()=>{
'use strict';
function apply(){
 const snap=document.getElementById('coinSnapshot');const card=snap?.closest('.section-shell');if(card)card.style.display='none';
 const group=document.getElementById('coinTfGroup');if(group&&!group.querySelector('[data-tf="3m"]')){const b=document.createElement('button');b.className='tf';b.dataset.tf='3m';b.textContent='3M';const five=group.querySelector('[data-tf="5m"]');group.insertBefore(b,five||null)}
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',apply,{once:true});else apply();
})();
