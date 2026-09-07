(()=>{
'use strict';
const parts=location.pathname.split('/').filter(Boolean),KEY=(parts[2]||'').toLowerCase();
const num=v=>Number(v||0),esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[c]));
function money(v){const n=num(v),a=Math.abs(n),sg=n>0?'+':n<0?'−':'';if(a>=1e12)return sg+(a/1e12).toFixed(2)+'조원';if(a>=1e8)return sg+(a/1e8).toFixed(1)+'억원';if(a>=1e4)return sg+(a/1e4).toFixed(1)+'만원';return sg+Math.round(a).toLocaleString('ko-KR')+'원'}
function render(d){
 const row=(d?.items||{})[KEY],box=document.getElementById('indexFlowSummary');if(!row||!box||!['kospi','kosdaq'].includes(KEY))return;const latest=row.latest||{},cum=row.cumulative||{};
 const defs=[['person','개인'],['foreign','외국인'],['institution','기관']];if(!defs.some(([k])=>latest[k]!=null))return;
 box.innerHTML=defs.map(([k,label])=>{const v=num(latest[k]),c=cum[k];return `<div><small>${label} 최근 순매수</small><b class="${v>=0?'pos':'neg'}">${money(v)}</b><span>${c==null?'':`약 1개월 누적 ${esc(money(c))}`}</span></div>`}).join('');
 const st=document.getElementById('indexFlowStatus');if(st&&row.asof)st.textContent=`${row.asof} · ${row.source||'시장 투자자 수급'}`;
}
if(!window.__NAMUH_INDEX_V361_FETCH__){window.__NAMUH_INDEX_V361_FETCH__=true;const nativeFetch=window.fetch.bind(window);window.fetch=async(...args)=>{const res=await nativeFetch(...args);try{const u=String(args?.[0] instanceof Request?args[0].url:args?.[0]||'');if(u.includes('/api/v343/market-flow'))res.clone().json().then(d=>setTimeout(()=>render(d),80)).catch(()=>{})}catch(_){}return res}}
})();
