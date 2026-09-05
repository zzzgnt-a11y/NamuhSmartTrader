const $=id=>document.getElementById(id),esc=s=>String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;"}[c]));
const won=n=>"₩"+Math.round(Number(n||0)).toLocaleString("ko-KR"),pct=n=>(Number(n||0)>=0?"+":"")+Number(n||0).toFixed(2)+"%";
let settingsInitialized=false,currentCoinEquity=1500000;
try{localStorage.setItem("GY_MARKET","COIN")}catch(_){};
function goMode(m){try{localStorage.setItem("GY_MARKET",m)}catch(_){};if(m==="COIN")location.href="/coin";else location.href="/"}
function fmtPrice(n){const v=Number(n||0);return v>=1000?won(v):v.toLocaleString(undefined,{maximumFractionDigits:8})+"원"}
function compact(n){const v=Number(n||0);if(v>=1e12)return (v/1e12).toFixed(1)+"조";if(v>=1e8)return (v/1e8).toFixed(0)+"억";if(v>=1e4)return (v/1e4).toFixed(0)+"만";return Math.round(v).toLocaleString()}
function marketCard(x){const c=Number(x.change_pct||0);return `<article class="coin-market-card" data-coin="${esc(x.code)}"><div class="coin-symbol"><b>${esc(x.code)}</b><small>${esc(x.name||x.code)}</small></div><strong>${fmtPrice(x.price)}</strong><span class="${c>=0?"pos":"neg"}">${pct(c)}</span><div class="coin-vol">24H ${compact(x.quote_volume)}원</div><div class="chart-hint">차트 ↗</div></article>`}
function candidateCard(x,i,entryScore){const c=Number(x.change_pct||0),sp=x.spread_pct==null?"-":Number(x.spread_pct).toFixed(3)+"%",pass=Number(x.score||0)>=entryScore;return `<article class="candidate coin-candidate ${pass?"entry-ready":""}" data-coin="${esc(x.code)}"><div class="candidate-top"><div class="candidate-name"><b>${i+1}. ${esc(x.name||x.code)}</b><small>${esc(x.code)} · COINONE KRW</small></div><div class="score-badge">${Number(x.score||0).toFixed(0)}</div></div><div class="reason-row">${(x.reasons||[]).map(r=>`<span class="pill">${esc(r)}</span>`).join("")}</div><div class="metrics"><div class="metric"><span>현재가</span><b>${fmtPrice(x.price)}</b></div><div class="metric"><span>24H</span><b class="${c>=0?"pos":"neg"}">${pct(c)}</b></div><div class="metric"><span>체결강도</span><b>${Number(x.volume_power||0).toFixed(0)}</b></div><div class="metric"><span>스프레드</span><b>${sp}</b></div><div class="metric"><span>거래대금</span><b>${compact(x.quote_volume)}원</b></div></div></article>`}
function posRow(p){return `<div class="position-row" data-coin="${esc(p.code)}"><div><b>${esc(p.name||p.code)}</b> <span class="market-badge">COIN</span> <span class="strategy-tag">${esc(p.strategy||"COIN_SCALP")}</span><br><small>${esc(p.code)} · ${Number(p.qty||0).toLocaleString(undefined,{maximumFractionDigits:8})}개 · 24H</small></div><div class="position-right"><b class="${p.pnl>=0?"pos":"neg"}">${pct(p.pnl_pct)}</b><br><small>${won(p.pnl)} · ${fmtPrice(p.current_price)}</small></div></div>`}
function tradeRow(t){return `<div class="coin-trade-row"><div><span class="trade-side ${t.side==="BUY"?"buy":"sell"}">${esc(t.side)}</span><b>${esc(t.name||t.code)}</b><small>${esc(t.date)} ${esc(t.time)} · ${esc(t.reason||t.strategy||"")}</small></div><div><b>${fmtPrice(t.price)}</b><small class="${Number(t.pnl||0)>=0?"pos":"neg"}">${t.side==="SELL"?won(t.pnl)+" · "+pct(t.pnl_pct):won(t.gross_krw)}</small></div></div>`}
async function saveCoinSettings(){
  const raw=String($("coinBudget")?.value||"").replace(/,/g,"").trim();
  const amount=raw===""?null:Number(raw.replace(/\D/g,""));
  const entryScore=Number($("coinEntryScore")?.value||66);
  if(amount!==null&&(!Number.isFinite(amount)||amount<0||amount>currentCoinEquity)){alert(`0~현재 자산 ${won(currentCoinEquity)} 범위로 입력하거나 비워주세요.`);return}
  if(!Number.isFinite(entryScore)||entryScore<50||entryScore>90){alert("진입 기준점수는 50~90 사이로 설정해주세요.");return}
  const body={amount,auto_max_if_unset:Boolean($("coinAutoMaxIfUnset")?.checked),auto_trade_enabled:Boolean($("coinAutoTrade")?.checked),entry_score:entryScore};
  const r=await fetch("/api/coin/settings",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
  const d=await r.json().catch(()=>({}));
  if(!r.ok){alert(d.detail||"코인 운용설정 저장 실패");return}
  settingsInitialized=false;await refresh();
}
function render(d){
  const a=d.account||{},h=d.health||{},settings=d.settings||{},top=d.candidates?.[0],entryScore=Number(a.entry_score??settings.entry_score??66),autoOn=Boolean(a.auto_trade_enabled??settings.auto_trade_enabled);
  currentCoinEquity=Math.max(0,Number(a.equity||0));
  $("coinEquity").textContent=won(a.equity);$("coinPnl").textContent=`${won(a.pnl)} · ${pct(a.pnl_pct)}`;$("coinPnl").className=Number(a.pnl)>=0?"pos":"neg";
  $("heroCoinBudget").textContent=won(a.effective_budget);$("accountInitial").textContent=won(a.initial_cash);$("accountCash").textContent=won(a.cash);$("accountHeld").textContent=won(a.held_cost);$("accountAvailable").textContent=won(a.available_budget);
  $("coinTopSignal").textContent=top?`${top.code} ${Number(top.score).toFixed(0)}점`:"분석 중";$("coinLeadingSignal").textContent=top?`${top.name||top.code} · ${Number(top.score).toFixed(0)}점`:"분석 중";
  $("coinHealth").textContent=h.ws_connected?"WS LIVE":h.rest_connected?"REST LIVE":"연결 대기";$("coinHealthSub").textContent=`${h.priced_count||0}종목 · 자동매매 ${autoOn?"ON":"OFF"}`;$("updatedClock").textContent=new Date().toLocaleTimeString("ko-KR",{hour12:false})+" LIVE";
  $("currentCoinBudget").textContent=`현재 운용값: ${won(a.effective_budget)}`;$("currentEntryScore").textContent=`${entryScore.toFixed(0)}점`;$("coinEntryRuleText").textContent=`${entryScore.toFixed(0)}점 이상 진입 · 보유 종목 수 제한 없음`;$("entryRule").textContent=`진입 ≥ ${entryScore.toFixed(0)}`;
  if(!settingsInitialized){$("coinBudget").value=a.explicit_budget==null?"":a.explicit_budget;$("coinAutoMaxIfUnset").checked=Boolean(a.auto_max_if_unset);$("coinAutoTrade").checked=autoOn;$("coinEntryScore").value=entryScore.toFixed(0);settingsInitialized=true}
  $("coinMarketGrid").innerHTML=(d.market||[]).map(marketCard).join("")||'<div class="empty">코인원 시세 연결 중</div>';
  $("coinCandidateList").innerHTML=(d.candidates||[]).map((x,i)=>candidateCard(x,i,entryScore)).join("")||'<div class="empty">후보 데이터 축적 중</div>';
  $("coinHoldingSummary").textContent=`${(a.positions||[]).length}종 보유 · 보유원가 ${won(a.held_cost)}`;
  $("coinPositions").innerHTML=(a.positions||[]).map(posRow).join("")||'<div class="empty">현재 코인 보유 없음</div>';
  $("coinTrades").innerHTML=(a.trades||[]).slice(0,80).map(tradeRow).join("")||'<div class="empty">아직 코인 모의매매 내역이 없습니다.</div>';
}
async function refresh(){try{const r=await fetch("/api/coin/state",{cache:"no-store"});const d=await r.json();if(!r.ok)throw new Error(d.detail||r.status);render(d)}catch(e){console.error(e);$("coinHealth").textContent="연결 오류";$("coinHealthSub").textContent=String(e.message||e)}}
document.addEventListener("click",e=>{const c=e.target.closest?.("[data-coin]");if(c){location.href="/coin/"+encodeURIComponent(c.dataset.coin);return}const s=e.target.closest?.("[data-scroll]");if(s)$(s.dataset.scroll)?.scrollIntoView({behavior:"smooth",block:"start"})});
$("saveCoinSettingsBtn")?.addEventListener("click",saveCoinSettings);$("krModeLabel")?.addEventListener("click",()=>goMode("KR"));$("usModeLabel")?.addEventListener("click",()=>goMode("US"));$("coinModeLabel")?.addEventListener("click",()=>goMode("COIN"));
refresh();setInterval(refresh,5000);
