(function(){
  const q=s=>document.querySelector(s),esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[c]));
  const parts=location.pathname.split('/').filter(Boolean),symbol=(parts[1]||'BTC').toUpperCase();
  function inject(){
    const main=q('main.detail-page');if(!main||q('#v33CoinScore'))return;
    const sec=document.createElement('section');sec.id='v33CoinScore';sec.className='section-shell v33-score-panel';
    sec.innerHTML='<div class="section-head"><div><span class="section-index">SCORE</span><div><small>GY ENTRY SCORE BREAKDOWN</small><h2>총점 · 세부 점수</h2></div></div><b id="v33CoinTotal">분석 중</b></div><div id="v33CoinBars" class="v33-score-bars"><div class="empty">점수 분석 수신 중</div></div>';
    const chart=q('.index-chart-panel');chart?.insertAdjacentElement('afterend',sec);
  }
  async function load(){
    inject();
    try{
      const r=await fetch(`/api/coin/${encodeURIComponent(symbol)}?interval=1d&size=180`,{cache:'no-store'});const d=await r.json();if(!r.ok)throw new Error(d.detail||r.status);const c=d.candidate||{},rows=c.score_breakdown||[];
      q('#v33CoinTotal').textContent=`총점 ${Number(c.score_total??c.score??0).toFixed(1)}점`;
      q('#v33CoinBars').innerHTML=rows.length?rows.map(x=>{const score=Number(x.score||0),max=Math.max(1,Number(x.max||100)),w=Math.max(0,Math.min(100,score/max*100));return `<div class="v33-score-row"><div><span>${esc(x.label)}</span><b>${score.toFixed(1)} / ${max.toFixed(0)}</b></div><div class="v33-score-track"><i style="width:${w}%"></i></div></div>`}).join(''):'<div class="empty">세부 점수 데이터 축적 중</div>';
    }catch(e){console.error(e);if(q('#v33CoinBars'))q('#v33CoinBars').innerHTML='<div class="empty">점수 분석 연결 대기</div>'}
  }
  inject();load();setInterval(load,30000);
})();
