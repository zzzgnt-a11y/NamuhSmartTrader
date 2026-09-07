(()=>{
'use strict';
const labels={'1m':'1분','3m':'3분','5m':'5분','20m':'20분','1d':'일봉','종합':'복합'};
function renderScores(d){
 const box=document.getElementById('scoreGrid');if(!box)return;const s=d?.scores||{},order=['1m','3m','5m','20m','1d'];if(s['종합']!=null)order.push('종합');
 box.innerHTML=order.map(k=>{const v=s[k],active=document.querySelector(`[data-tf="${k}"]`)?.classList.contains('active');return `<div class="score-tile ${active?'active':''}"><span>${labels[k]||k}</span><strong>${v==null?'계산중':Number(v).toFixed(0)}</strong></div>`}).join('');
}
function cleanup(){document.querySelectorAll('.v348-disc-strip').forEach(x=>x.remove());const ov=document.getElementById('v348ChartEvents');if(ov)ov.style.display='none';if(!document.getElementById('v361StockStyle')){const s=document.createElement('style');s.id='v361StockStyle';s.textContent='.v348-disc-strip,#v348ChartEvents{display:none!important}';document.head.appendChild(s)}}
if(!window.__NAMUH_STOCK_V361_FETCH__){window.__NAMUH_STOCK_V361_FETCH__=true;const nativeFetch=window.fetch.bind(window);window.fetch=async(...args)=>{const res=await nativeFetch(...args);try{const u=String(args?.[0] instanceof Request?args[0].url:args?.[0]||'');if(u.includes('/api/v344/stock/'))res.clone().json().then(d=>setTimeout(()=>{cleanup();renderScores(d)},80)).catch(()=>{})}catch(_){}return res}}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',cleanup,{once:true});else cleanup();
})();
