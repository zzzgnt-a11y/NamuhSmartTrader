(()=>{
'use strict';
const $=s=>document.querySelector(s);
function mode(){return $('#usModeLabel')?.classList.contains('active')?'US':'KR'}
function installStyle(){
 if($('#v365MarketUiStyle'))return;
 const st=document.createElement('style');st.id='v365MarketUiStyle';st.textContent=`
/* Time AI stays visible but is no longer presented as nested boxed cards. */
#v364Grid>.v364-panel:first-child{border:0!important;background:transparent!important;padding:0!important}
#v364Grid>.v364-panel:first-child .v364-head{margin-bottom:6px!important}
#v364Times{gap:0!important;overflow-x:auto!important;padding:2px 0 4px!important}
#v364Times .v364-time{min-width:112px!important;border:0!important;border-right:1px solid rgba(80,100,140,.12)!important;border-radius:0!important;background:transparent!important;padding:2px 10px!important;box-shadow:none!important}
#v364Times .v364-time:first-child{padding-left:0!important}
#v364Times .v364-time:last-child{border-right:0!important}
#v364Times .v364-time strong{font-size:15px!important}
#v364Times .v364-time span{font-size:10px!important}
#v364Times .v364-time small{font-size:9px!important}
#v364Grid.v365-us{grid-template-columns:1fr!important}
#v364Grid.v365-us #v364FlowPanel{display:none!important}
`;
 document.head.appendChild(st);
}
function sync(){
 installStyle();
 const g=$('#v364Grid'),flow=$('#v364FlowPanel');
 const us=mode()==='US';
 if(g)g.classList.toggle('v365-us',us);
 if(flow){flow.hidden=us;flow.style.display=us?'none':''}
}
function init(){
 sync();
 $('#krModeLabel')?.addEventListener('click',()=>setTimeout(sync,80));
 $('#usModeLabel')?.addEventListener('click',()=>setTimeout(sync,80));
 document.addEventListener('visibilitychange',()=>{if(!document.hidden)sync()});
 setInterval(sync,3000);
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});else init();
})();
