(()=>{
'use strict';
const $=s=>document.querySelector(s);
function mode(){return $('#usModeLabel')?.classList.contains('active')?'US':'KR'}
function installStyle(){
 if($('#v365MarketUiStyle'))return;
 const st=document.createElement('style');st.id='v365MarketUiStyle';st.textContent=`
/* Main time-bucket AI cards are intentionally removed. Detailed 1m/3m/5m/20m/1d scores remain on stock detail pages. */
#v364Grid{grid-template-columns:1fr!important}
#v364Grid>.v364-panel:first-child{display:none!important}
#v364Grid.v365-us{display:none!important}
#v364Grid #v364FlowPanel{display:block}
`;
 document.head.appendChild(st);
}
function sync(){
 installStyle();
 const g=$('#v364Grid'),flow=$('#v364FlowPanel');
 const us=mode()==='US';
 if(g){g.classList.toggle('v365-us',us);g.style.display=us?'none':'grid'}
 if(flow){flow.hidden=us;flow.style.display=us?'none':'block'}
}
function init(){
 sync();
 $('#krModeLabel')?.addEventListener('click',()=>setTimeout(sync,40));
 $('#usModeLabel')?.addEventListener('click',()=>setTimeout(sync,40));
 document.addEventListener('visibilitychange',()=>{if(!document.hidden)sync()});
 setInterval(sync,1000);
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});else init();
})();
