(()=>{
'use strict';
const $=s=>document.querySelector(s);
let raf=0,obs=null;

function layout(){
  const box=$('#v34SearchBox'),line=box?.querySelector('.v34-search-line'),r=$('#v34SearchResults');
  if(!box||!line||!r)return;

  if(r.parentElement!==document.body)document.body.appendChild(r);

  const rect=line.getBoundingClientRect();
  const vv=window.visualViewport;
  const viewTop=vv?.offsetTop||0;
  const viewH=vv?.height||window.innerHeight;
  const viewBottom=viewTop+viewH;
  const top=Math.round(rect.bottom+6);
  const left=Math.max(8,Math.round(rect.left));
  const right=Math.min(window.innerWidth-8,Math.round(rect.right));
  const width=Math.max(180,right-left);
  const avail=Math.max(72,Math.floor(viewBottom-top-10));
  const maxH=Math.min(360,avail);

  const wanted={
    position:'fixed',left:left+'px',right:'auto',top:top+'px',bottom:'auto',
    width:width+'px',maxHeight:maxH+'px',zIndex:'2147483000',
    margin:'0',boxSizing:'border-box'
  };
  for(const [k,v] of Object.entries(wanted)){
    if(r.style[k]!==v)r.style.setProperty(k.replace(/[A-Z]/g,m=>'-'+m.toLowerCase()),v,'important');
  }
}

function schedule(){
  if(raf)return;
  raf=requestAnimationFrame(()=>{raf=0;layout()});
}

function hook(){
  const r=$('#v34SearchResults'),input=$('#v34SearchInput');
  if(!r||!input)return false;
  layout();
  if(obs)obs.disconnect();
  obs=new MutationObserver(schedule);
  obs.observe(r,{attributes:true,attributeFilter:['style','class']});
  input.addEventListener('focus',schedule);
  input.addEventListener('input',schedule);
  input.addEventListener('compositionend',schedule);
  return true;
}

function init(){
  let tries=0;
  const t=setInterval(()=>{
    tries++;
    if(hook()||tries>80)clearInterval(t);
  },100);
  window.addEventListener('resize',schedule,{passive:true});
  window.addEventListener('scroll',schedule,{passive:true});
  window.visualViewport?.addEventListener('resize',schedule,{passive:true});
  window.visualViewport?.addEventListener('scroll',schedule,{passive:true});
}

if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});else init();
})();
