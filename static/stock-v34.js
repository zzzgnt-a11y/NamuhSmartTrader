(function(){
  const q=s=>document.querySelector(s),esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[c]));
  const parts=location.pathname.split('/').filter(Boolean),market=(parts[1]||'KR').toUpperCase(),code=(parts[2]||'').toUpperCase();
  function summary(e){if(e.blocked)return '중대 악재 · 신규진입 차단';if(e.sentiment==='positive')return '호재 +5점 · 5개 1분봉 상승 확인 후 진입';if(e.sentiment==='negative')return '악재 -5점';return '중립 0점'}
  async function loadEvents(){
    const box=q('#stockEvents');if(!box)return;
    try{const r=await fetch(`/api/v34/events/${market}/${encodeURIComponent(code)}`,{cache:'no-store'}),d=await r.json(),rows=d.items||[];box.innerHTML=rows.length?rows.map(e=>`<div class="event-item stock-event-item"><div class="event-head"><span class="event-label ${e.sentiment==='negative'?'negative':''}">${esc(e.label)} ${Number(e.score||0)?(Number(e.score)>0?'+':'')+Number(e.score).toFixed(0):''}</span><small>${esc(e.date||'')} · ${esc(e.source||'')}</small></div><b>${esc(e.title)}</b><div class="event-ai-summary"><strong>진입 반영</strong><span>${esc(summary(e))}</span></div>${e.url?`<a href="${esc(e.url)}" target="_blank" rel="noopener">공시 원문 ↗</a>`:''}</div>`).join(''):'<div class="empty">최근 공시 없음 또는 수신 대기</div>'}catch(e){console.error(e)}
  }
  async function loadTrend(){try{const r=await fetch(`/api/v34/trend/${market}/${encodeURIComponent(code)}`,{cache:'no-store'}),d=await r.json(),box=q('#analysisReasons');if(!box)return;let badge=q('#v34TrendBadge');if(!badge){badge=document.createElement('span');badge.id='v34TrendBadge';box.prepend(badge)}badge.textContent=d.ready?(d.uptrend?`5분 상승추세 · ${Number(d.return_pct||0).toFixed(2)}%`:'5분 상승확인 대기'):'1분봉 5개 축적 중';badge.className=d.uptrend?'v34-trend-up':'v34-trend-wait'}catch(_){} }
  function init(){loadEvents();loadTrend();setInterval(loadEvents,30000);setInterval(loadTrend,5000)}
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init);else init();
})();
