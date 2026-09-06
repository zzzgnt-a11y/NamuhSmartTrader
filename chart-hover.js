(()=>{
'use strict';

/*
  Interaction-only layer.
  Hides old hover popup boxes and adds a horizontal guide following mouse Y.
  It does not change page/background/font/card palette.
*/
const targets=[
  ['candleCanvas','chartTooltip'],
  ['investorFlowCanvas','investorFlowTooltip'],
  ['indexCandleCanvas','indexTooltip'],
  ['indexFlowCanvas','indexFlowTooltip']
];

function setup(canvasId,tooltipId){
  const canvas=document.getElementById(canvasId);
  if(!canvas) return;

  const tooltip=document.getElementById(tooltipId);
  if(tooltip){
    tooltip.style.setProperty('display','none','important');
  }

  const wrap=canvas.parentElement;
  if(!wrap) return;

  if(getComputedStyle(wrap).position==='static'){
    wrap.style.position='relative';
  }

  let line=wrap.querySelector(`[data-gy-hover-line="${canvasId}"]`);
  if(!line){
    line=document.createElement('div');
    line.dataset.gyHoverLine=canvasId;
    line.setAttribute('aria-hidden','true');
    Object.assign(line.style,{
      position:'absolute',
      height:'0',
      borderTop:'1px solid currentColor',
      opacity:'.35',
      pointerEvents:'none',
      display:'none',
      zIndex:'8'
    });
    wrap.appendChild(line);
  }

  function syncX(){
    const cr=canvas.getBoundingClientRect();
    const wr=wrap.getBoundingClientRect();
    line.style.left=`${Math.max(0,cr.left-wr.left)}px`;
    line.style.width=`${Math.max(0,cr.width)}px`;
  }

  function hide(){
    line.style.display='none';
  }

  function move(e){
    const cr=canvas.getBoundingClientRect();
    if(
      e.clientX<cr.left || e.clientX>cr.right ||
      e.clientY<cr.top || e.clientY>cr.bottom
    ){
      hide();
      return;
    }

    const wr=wrap.getBoundingClientRect();
    syncX();
    const y=Math.max(0,Math.min(wr.height,e.clientY-wr.top));
    line.style.top=`${y}px`;
    line.style.display='block';
  }

  syncX();

  canvas.addEventListener('mousemove',move,{passive:true});
  canvas.addEventListener('mouseleave',hide,{passive:true});

  window.addEventListener('resize',()=>{
    syncX();
    hide();
  },{passive:true});

  if('ResizeObserver' in window){
    const ro=new ResizeObserver(()=>{
      syncX();
      hide();
    });
    ro.observe(canvas);
    ro.observe(wrap);
    canvas._gyHoverResizeObserver=ro;
  }
}

function init(){
  targets.forEach(([canvasId,tooltipId])=>setup(canvasId,tooltipId));
}

if(document.readyState==='loading'){
  document.addEventListener('DOMContentLoaded',init,{once:true});
}else{
  init();
}
})();
