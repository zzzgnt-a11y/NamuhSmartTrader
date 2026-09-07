(()=>{
'use strict';
const $=s=>document.querySelector(s);
let last='';
function signed(n){const v=Math.round(Number(n||0));return (v>0?'+':v<0?'-':'')+Math.abs(v).toLocaleString('ko-KR')}
function renderFlow(d){
 if(String(d?.market||'KR').toUpperCase()!=='KR')return;
 const f=d.investor_numeric||{},flow=d.flow||{};
 const vals=[
   ['개인',f.person??flow.person_net],
   ['외국인',f.foreign??flow.foreign_net],
   ['기관',f.institution??flow.institution_net],
 ];
 const key=vals.map(x=>x[1]).join('|');if(key===last)return;last=key;
 const box=$('#flowGrid');if(box)box.innerHTML=vals.map(([l,v])=>`<div><span>${l}</span><b class="${Number(v||0)>=0?'pos':'neg'}">${signed(v)}주</b></div>`).join('');
 const cap=$('#flowCaption');if(cap)cap.textContent='NHPLUG 투자자 순매수';
}
function renderChartMeta(d){
 const tf=String(d?.timeframe||'1d').toLowerCase(),targets=d?.intraday_targets||{'1m':60,'3m':30,'5m':30,'20m':30};
 if(!(tf in targets))return;
 const n=Array.isArray(d?.bars)?d.bars.length:Number(d?.intraday_counts?.[tf]||0),target=Number(targets[tf]||0);
 const s=$('#chartStatus');if(s)s.textContent=`${tf.replace('m','분')} · ${n}/${target} 캔들 · 공식 OHLCV`;
}
function renderCombined(d){
 const v=d?.combined_score;if(v==null)return;
 const grid=$('#scoreGrid');if(!grid)return;
 let tile=[...grid.querySelectorAll('.score-tile')].find(x=>x.querySelector('span')?.textContent==='종합');
 if(!tile){tile=document.createElement('div');tile.className='score-tile v360-combined';tile.innerHTML='<span>종합</span><strong></strong>';grid.prepend(tile)}
 tile.querySelector('strong').textContent=Number(v).toFixed(0);
}
function apply(d){setTimeout(()=>{renderFlow(d);renderChartMeta(d);renderCombined(d)},0)}
function currentTf(){return document.querySelector('.tf.active')?.dataset.tf||'1d'}
function pull(){const p=location.pathname.split('/').filter(Boolean),m=(p[1]||'KR').toUpperCase(),c=(p[2]||'').toUpperCase();if(!c)return;fetch(`/api/v344/stock/${encodeURIComponent(m)}/${encodeURIComponent(c)}?timeframe=${encodeURIComponent(currentTf())}&days=60`,{cache:'no-store'}).then(r=>r.ok?r.json():null).then(d=>d&&apply(d)).catch(()=>{})}
if(!window.__NAMUH_V360_STOCK_FETCH__){window.__NAMUH_V360_STOCK_FETCH__=true;const native=window.fetch.bind(window);window.fetch=async(...args)=>{const res=await native(...args);try{const u=String(args?.[0] instanceof Request?args[0].url:args?.[0]||'');if(u.includes('/api/v344/stock/')||u.includes('/api/stock/'))res.clone().json().then(apply).catch(()=>{})}catch(_){}return res}}
function init(){document.querySelectorAll('.tf').forEach(b=>b.addEventListener('click',()=>setTimeout(pull,40)));pull()}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});else init();
})();
