(function(){
  const q=s=>document.querySelector(s),esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[c]));
  const parts=location.pathname.split('/').filter(Boolean),symbol=(parts[1]||'BTC').toUpperCase();
  function detailRows(rows){return (rows||[]).map(x=>{const score=Number(x.score||0),max=Math.max(1,Number(x.max||1)),w=Math.max(0,Math.min(100,score/max*100));return `<div class="v34-mini-score"><span>${esc(x.label)}</span><div><i style="width:${w}%"></i></div><b>${score.toFixed(1)} / ${max.toFixed(0)}</b></div>`}).join('')}
  function inject(){
    const old=q('#v33CoinScore');if(old)old.classList.add('v34-hidden');
    const main=q('main.detail-page');if(!main||q('#v34CoinScore'))return;
    const sec=document.createElement('section');sec.id='v34CoinScore';sec.className='section-shell v34-score-panel';
    sec.innerHTML='<div class="section-head"><div><span class="section-index">SCORE</span><div><small>GY COIN ENTRY SCORE</small><h2>Value / Technical</h2></div></div><b id="v34CoinTotal">분석 중</b></div><div class="v34-score-summary"><div><span>VALUE SCORE</span><div class="v34-score-track"><i id="v34ValueFill"><b id="v34ValueText">0 / 30</b></i></div></div><div><span>TECHNICAL SCORE</span><div class="v34-score-track"><i id="v34TechFill"><b id="v34TechText">0 / 70</b></i></div></div></div><div class="v34-score-details"><section><h3>VALUE DETAIL</h3><div id="v34ValueDetails"></div></section><section><h3>TECHNICAL DETAIL</h3><div id="v34TechDetails"></div></section></div>';
    (q('.index-chart-panel')||q('main.detail-page')).insertAdjacentElement('afterend',sec);
  }
  async function load(){inject();try{const r=await fetch(`/api/coin/${encodeURIComponent(symbol)}?interval=1d&size=180`,{cache:'no-store'});const d=await r.json(),c=d.candidate||{},v=Math.max(0,Math.min(30,Number(c.value_score||0))),t=Math.max(0,Math.min(70,Number(c.technical_score||0)));q('#v34CoinTotal').textContent=`TOTAL · ${Number(c.score_total??c.score??0).toFixed(1)}점`;q('#v34ValueFill').style.width=(v/30*100)+'%';q('#v34TechFill').style.width=(t/70*100)+'%';q('#v34ValueText').textContent=`${v.toFixed(1)} / 30`;q('#v34TechText').textContent=`${t.toFixed(1)} / 70`;q('#v34ValueDetails').innerHTML=detailRows(c.value_breakdown);q('#v34TechDetails').innerHTML=detailRows(c.technical_breakdown)||'<div class="empty">기술지표 축적 중</div>'}catch(e){console.error(e)}}
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',()=>{inject();load()});else{inject();load()}setInterval(load,30000);
})();
