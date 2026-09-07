(function(){
  const q=s=>document.querySelector(s),esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[c]));
  const won=n=>'₩'+Math.round(Number(n||0)).toLocaleString('ko-KR');
  const pct=n=>(Number(n||0)>=0?'+':'')+Number(n||0).toFixed(2)+'%';
  const fmt=n=>{const v=Number(n||0);return v>=1000?won(v):v.toLocaleString(undefined,{maximumFractionDigits:8})+'원'};
  const compact=n=>{const v=Number(n||0);if(v>=1e12)return(v/1e12).toFixed(1)+'조';if(v>=1e8)return(v/1e8).toFixed(0)+'억';if(v>=1e4)return(v/1e4).toFixed(0)+'만';return Math.round(v).toLocaleString()};
  function newCandidate(x,i,entry){
    const c=Number(x.change_pct||0),sc=x.score_components||{},ready=Number(x.score||0)>=entry&&x.entry_gate_pass;
    return `<article class="candidate coin-candidate ${ready?'entry-ready':''}" data-coin="${esc(x.code)}"><div class="candidate-top"><div class="candidate-name"><b>${i+1}. ${esc(x.name||x.code)}</b><small>${esc(x.code)} · COINONE · 20/15/20/45</small></div><div class="score-badge">${Number(x.score||0).toFixed(0)}</div></div><div class="reason-row"><span class="pill">일봉 ${Number(sc.daily20||0).toFixed(0)}/20</span><span class="pill">거래량 ${Number(sc.volume15||0).toFixed(0)}/15</span><span class="pill">체결 ${Number(sc.execution20||0).toFixed(0)}/20</span><span class="pill">기술 ${Number(sc.technical45||0).toFixed(0)}/45</span></div><div class="metrics"><div class="metric"><span>현재가</span><b>${fmt(x.price)}</b></div><div class="metric"><span>최종 AI</span><b>${Number(x.score||0).toFixed(0)} / 100</b></div><div class="metric"><span>체결강도</span><b>${Number(x.volume_power||0).toFixed(1)}</b></div><div class="metric"><span>거래량 전일비</span><b>${Number(x.volume_ratio||0).toFixed(2)}배</b></div><div class="metric"><span>기술 원점수</span><b>${Number(x.technical_score_100||0).toFixed(0)} / 100</b></div><div class="metric"><span>24H</span><b class="${c>=0?'pos':'neg'}">${pct(c)}</b></div></div><div class="reason-row"><span class="pill">${esc(x.entry_gate_stage||'조건 확인 중')}</span><span class="pill">거래대금 ${compact(x.quote_volume)}원</span></div></article>`;
  }
  function ownMain(){
    if(!q('#coinCandidateList'))return;
    try{window.candidateCard=newCandidate;candidateCard=newCandidate}catch(_){}
    const fix=()=>{
      const head=q('#coinSignalSec .section-head b');if(head)head.textContent='일봉20 + 거래량15 + 체결20 + 기술45';
      const rule=q('#coinEntryRuleText');if(rule){const e=q('#currentEntryScore')?.textContent||'66점';rule.textContent=`${e} 이상 + 체결강도 규칙 통과 · 1분봉 Gate 없음`;}
      const mode=q('#coinSignalSec .section-head small');if(mode)mode.textContent='COIN 20/15/20/45 SIGNAL';
    };fix();setInterval(fix,700);
  }
  async function detailLoad(){
    if(!document.body.classList.contains('coin-detail-body'))return;
    q('#v34CoinScore')?.classList.add('v34-hidden');q('.v341-total-card')?.classList.add('v34-hidden');
    let box=q('#tech100Detail');if(!box){box=document.createElement('section');box.id='tech100Detail';box.className='section-shell v34-score-panel';(q('.index-chart-panel')||q('main.detail-page'))?.insertAdjacentElement('afterend',box);}
    const parts=location.pathname.split('/').filter(Boolean),sym=(parts[1]||'BTC').toUpperCase();
    try{
      const r=await fetch(`/api/coin/${encodeURIComponent(sym)}?interval=1m&size=120`,{cache:'no-store'}),d=await r.json(),x=d.candidate||{},sc=x.score_components||{};
      box.innerHTML=`<div class="section-head"><div><span class="section-index">COIN100</span><div><small>COIN ENTRY ENGINE</small><h2>일봉20 · 거래량15 · 체결20 · 기술45</h2></div></div><b>뉴스/공시/섹터/프로그램/1분봉 Gate 없음</b></div><div class="v341-total-score"><strong>${Number(x.score||0).toFixed(1)}</strong><span>점 / 100</span></div><div class="metrics"><div class="metric"><span>일봉</span><b>${Number(sc.daily20||0).toFixed(1)} / 20</b></div><div class="metric"><span>거래량</span><b>${Number(sc.volume15||0).toFixed(1)} / 15</b></div><div class="metric"><span>체결강도</span><b>${Number(sc.execution20||0).toFixed(1)} / 20</b></div><div class="metric"><span>기술</span><b>${Number(sc.technical45||0).toFixed(1)} / 45</b></div></div><div class="reason-row"><span class="pill">110/105/100 즉시</span><span class="pill">95+ 30초 상승</span><span class="pill">90+ 60초 상승</span><span class="pill">90 미만 미진입</span><span class="pill">${esc(x.entry_gate_stage||'조건 확인 중')}</span></div>`;
    }catch(e){box.innerHTML='<div class="empty">코인 점수 데이터 수신 중</div>';}
  }
  function init(){ownMain();detailLoad();if(document.body.classList.contains('coin-detail-body'))setInterval(detailLoad,5000);}
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init);else init();
})();
