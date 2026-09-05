const $=id=>document.getElementById(id);
const esc=s=>String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;"}[c]));
const path=location.pathname.split("/").filter(Boolean),MARKET=(path[1]||"KR").toUpperCase(),CODE=(path[2]||"").toUpperCase();
try{localStorage.setItem("GY_MARKET",MARKET)}catch(_){}
document.body.dataset.market=MARKET;
let TF="1d",DATA=null,bars=[],zoom=1,offset=0,drag=false,lastX=0,pinchStart=null;
const canvas=$("candleCanvas"),ctx=canvas.getContext("2d"),tip=$("chartTooltip");
function money(v){return MARKET==="US"?"$"+Number(v||0).toLocaleString(undefined,{maximumFractionDigits:4}):Number(v||0).toLocaleString("ko-KR")+"원"}
function resize(){const r=canvas.parentElement.getBoundingClientRect(),dpr=Math.max(1,window.devicePixelRatio||1);canvas.width=Math.round(r.width*dpr);canvas.height=Math.round(r.height*dpr);canvas.style.width=r.width+"px";canvas.style.height=r.height+"px";ctx.setTransform(dpr,0,0,dpr,0,0);draw()}
function visibleBars(){
  const base=Math.min(bars.length,Math.max(20,Math.floor(90/zoom))),end=Math.max(base,Math.min(bars.length,bars.length-Math.round(offset)));
  return bars.slice(Math.max(0,end-base),end)
}
function draw(){
  const w=canvas.clientWidth,h=canvas.clientHeight;ctx.clearRect(0,0,w,h);
  const v=visibleBars();if(!v.length){ctx.fillStyle="#8498b3";ctx.font="12px sans-serif";ctx.fillText("공식 봉 데이터 축적 중",20,30);return}
  const max=Math.max(...v.map(x=>Number(x.high))),min=Math.min(...v.map(x=>Number(x.low))),span=max-min||1;
  const pad={l:12,r:62,t:18,b:28},cw=w-pad.l-pad.r,ch=h-pad.t-pad.b,step=cw/v.length,bw=Math.max(2,Math.min(12,step*.62));
  ctx.strokeStyle="rgba(139,169,206,.07)";ctx.lineWidth=1;
  for(let i=0;i<5;i++){const y=pad.t+ch*i/4;ctx.beginPath();ctx.moveTo(pad.l,y);ctx.lineTo(w-pad.r,y);ctx.stroke();
    const val=max-span*i/4;ctx.fillStyle="#6f829b";ctx.font="9px sans-serif";ctx.fillText(val.toLocaleString(undefined,{maximumFractionDigits:2}),w-pad.r+7,y+3)}
  v.forEach((b,i)=>{const x=pad.l+step*i+step/2,y=yv(Number(b.close)),yo=yv(Number(b.open)),yh=yv(Number(b.high)),yl=yv(Number(b.low));
    const up=Number(b.close)>=Number(b.open);ctx.strokeStyle=up?"#64e7a5":"#ff7e8d";ctx.fillStyle=ctx.strokeStyle;ctx.lineWidth=1;
    ctx.beginPath();ctx.moveTo(x,yh);ctx.lineTo(x,yl);ctx.stroke();const top=Math.min(y,yo),hh=Math.max(1,Math.abs(y-yo));ctx.fillRect(x-bw/2,top,bw,hh)});
  function yv(p){return pad.t+(max-p)/span*ch}
  const labels=[0,Math.floor(v.length/2),v.length-1].filter((x,i,a)=>a.indexOf(x)===i);
  ctx.fillStyle="#6f829b";ctx.font="9px sans-serif";labels.forEach(i=>{const b=v[i],x=pad.l+step*i+step/2;
    const raw=String(b.time||"");const label=raw.length===8?raw.slice(4,6)+"/"+raw.slice(6,8):new Date(Number(b.time)*1000).toLocaleTimeString("ko-KR",{hour:"2-digit",minute:"2-digit",hour12:false});
    ctx.fillText(label,Math.min(w-50,Math.max(5,x-15)),h-8)})
  canvas._view={bars:v,pad,step,bw,max,min,span};
}
function hover(clientX,clientY){
  const r=canvas.getBoundingClientRect(),x=clientX-r.left,y=clientY-r.top,V=canvas._view;if(!V||!V.bars.length)return;
  const i=Math.max(0,Math.min(V.bars.length-1,Math.floor((x-V.pad.l)/V.step))),b=V.bars[i];if(!b)return;
  tip.classList.remove("hide");tip.style.left=Math.min(r.width-170,Math.max(8,x+10))+"px";tip.style.top=Math.min(r.height-92,Math.max(8,y+10))+"px";
  tip.innerHTML=`<b>${esc(DATA?.name||CODE)}</b><span>O ${money(b.open)} · H ${money(b.high)}</span><span>L ${money(b.low)} · C ${money(b.close)}</span><span>VOL ${Number(b.volume||0).toLocaleString()}</span>`
}
canvas.addEventListener("wheel",e=>{e.preventDefault();zoom=Math.max(.7,Math.min(5,zoom*(e.deltaY<0?1.18:.85)));draw()},{passive:false});
canvas.addEventListener("mousedown",e=>{drag=true;lastX=e.clientX});window.addEventListener("mouseup",()=>drag=false);
window.addEventListener("mousemove",e=>{if(drag){offset=Math.max(0,Math.min(Math.max(0,bars.length-20),offset+(lastX-e.clientX)/8));lastX=e.clientX;draw()}hover(e.clientX,e.clientY)});
canvas.addEventListener("mouseleave",()=>tip.classList.add("hide"));canvas.addEventListener("dblclick",()=>{zoom=1;offset=0;draw()});
canvas.addEventListener("touchstart",e=>{if(e.touches.length===2){pinchStart=Math.abs(e.touches[0].clientX-e.touches[1].clientX)}else if(e.touches.length===1){drag=true;lastX=e.touches[0].clientX}},{passive:true});
canvas.addEventListener("touchmove",e=>{if(e.touches.length===2&&pinchStart){const d=Math.abs(e.touches[0].clientX-e.touches[1].clientX);zoom=Math.max(.7,Math.min(5,zoom*d/pinchStart));pinchStart=d;draw()}else if(e.touches.length===1&&drag){offset=Math.max(0,Math.min(Math.max(0,bars.length-20),offset+(lastX-e.touches[0].clientX)/7));lastX=e.touches[0].clientX;draw()}},{passive:true});
canvas.addEventListener("touchend",()=>{drag=false;pinchStart=null});
function render(d){
  DATA=d;bars=d.bars||[];document.body.dataset.market=MARKET;
  $("stockName").textContent=d.name||CODE;$("stockMeta").textContent=`${CODE} · ${d.sector||"-"} · ${MARKET}`;$("stockPrice").textContent=money(d.price);
  $("chartStatus").textContent=bars.length?`${TF.toUpperCase()} · ${bars.length}개 봉 · 서버 수신 공식 데이터`:"공식 데이터 축적 중";
  const labels={"1m":"1분","3m":"3분","5m":"5분","20m":"20분","1d":"일봉"};
  $("scoreGrid").innerHTML=Object.entries(d.scores||{}).map(([k,v])=>`<div class="score-tile ${k===TF?"active":""}"><span>${labels[k]||k}</span><strong>${v==null?"—":Number(v).toFixed(0)}</strong></div>`).join("");
  const a=d.analysis;$("analysisReasons").innerHTML=a?(a.reasons||[]).slice(0,10).map(x=>`<span>${esc(x)}</span>`).join(""):'<div class="empty">해당 봉 기준 AI 점수 데이터 축적 중</div>';
  const f=d.flow||{};$("flowCaption").textContent=MARKET==="KR"?"외국인·기관·프로그램·체결강도":"미장은 기술적 지표 중심";
  $("flowGrid").innerHTML=MARKET==="KR"?[
    ["외국인",Number(f.foreign_net||0).toLocaleString()],["기관",Number(f.institution_net||0).toLocaleString()],
    ["프로그램",Number(f.program_net||0).toLocaleString()],["체결강도",Number(f.execution_strength||0).toFixed(1)+"%"],["전일대비 거래량",f.volume_ratio==null?"대기":Number(f.volume_ratio).toFixed(0)+"%"]
  ].map(x=>`<div><span>${x[0]}</span><b>${x[1]}</b></div>`).join(""):`<div class="empty">미장은 외국인·기관·프로그램 수급을 단타점수에 사용하지 않습니다.</div>`;
  const br=a?.breakdown||{};$("breakdown").innerHTML=Object.entries(br).length?Object.entries(br).map(([k,v])=>`<div class="break-row"><span>${esc(k)}</span><div><i style="width:${Math.min(100,Number(v||0)*10)}%"></i></div><b>${Number(v||0).toFixed(1)}</b></div>`).join(""):'<div class="empty">점수 분해 대기</div>';
  $("stockEvents").innerHTML=(d.events||[]).length?d.events.map(e=>`<div class="event-item"><span class="event-label ${e.sentiment==="negative"?"negative":""}">${esc(e.label)}</span><b>${esc(e.title)}</b><small>${esc(e.date)} · AI ${Number(e.score||0).toFixed(1)}</small></div>`).join(""):'<div class="empty">최근 이벤트 없음 또는 DART 연결 대기</div>';
  resize()
}
async function load(tf=TF){TF=tf;document.querySelectorAll(".tf").forEach(b=>b.classList.toggle("active",b.dataset.tf===TF));try{const r=await fetch(`/api/stock/${MARKET}/${CODE}?timeframe=${TF}`,{cache:"no-store"});if(!r.ok)throw new Error(r.status);render(await r.json())}catch(e){console.error(e);$("chartStatus").textContent="종목 데이터 연결 오류"}}
document.querySelectorAll(".tf").forEach(b=>b.addEventListener("click",()=>{zoom=1;offset=0;load(b.dataset.tf)}));
$("backBtn").addEventListener("click",()=>{location.href="/"});window.addEventListener("resize",resize);
load();setInterval(()=>load(TF),5000);
