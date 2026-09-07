from __future__ import annotations

from pathlib import Path
import re

_INSTALLED = False
ROOT = Path(__file__).resolve().parent


def _patch_text(rel: str, fn):
    p = ROOT / rel
    if not p.exists():
        return False
    text = p.read_text(encoding='utf-8')
    new = fn(text)
    if new != text:
        p.write_text(new, encoding='utf-8')
        return True
    return False


def _patch_app(text: str) -> str:
    if 'GY_FAST_STATE_V1_' not in text:
        helper = r'''
let __fastCacheWriteAt=0;
const __fastStateKey=m=>`GY_FAST_STATE_V1_${m}`;
function __saveFastState(s){
  try{
    const now=Date.now(); if(now-__fastCacheWriteAt<4000)return; __fastCacheWriteAt=now;
    localStorage.setItem(__fastStateKey(s?.mode||MODE),JSON.stringify({ts:now,state:s}));
  }catch(_){}
}
function __restoreFastState(m=MODE){
  try{
    const x=JSON.parse(localStorage.getItem(__fastStateKey(m))||'null');
    if(!x?.state||x.state.mode!==m)return false;
    render(x.state);
    text('updatedClock',new Date(Number(x.ts||Date.now())).toLocaleTimeString('ko-KR',{hour12:false})+' · 즉시표시');
    return true;
  }catch(_){return false}
}
'''
        text = text.replace('async function refresh(force=false)', helper + '\nasync function refresh(force=false)', 1)

    text = text.replace(
        'MODE=m==="US"?"US":"KR";budgetInitialized=false;applyMode();await refresh(true)',
        'MODE=m==="US"?"US":"KR";budgetInitialized=false;applyMode();__restoreFastState(MODE);await refresh(true)'
    )

    # Save successful state responses, but never block rendering on storage.
    text = re.sub(
        r'const r=await fetch\(`/api/state\?market=\$\{MODE\}`\,\{cache:"no-store"\}\);if\(!r\.ok\)throw new Error\(`state \$\{r\.status\}`\);render\(await r\.json\(\)\)',
        'const r=await fetch(`/api/state?market=${MODE}`,{cache:"no-store"});if(!r.ok)throw new Error(`state ${r.status}`);const d=await r.json();render(d);__saveFastState(d)',
        text,
        count=1,
    )

    text = re.sub(
        r'document\.addEventListener\("DOMContentLoaded",\(\)=>\{applyMode\(\);bind\(\);refresh\(\);setInterval\(refresh,(?:1000|3000|5000|10000)\)\}\);',
        'document.addEventListener("DOMContentLoaded",()=>{applyMode();bind();__restoreFastState(MODE);requestAnimationFrame(()=>refresh());setInterval(refresh,1000)});',
        text,
        count=1,
    )
    return text


def _patch_v34(text: str) -> str:
    # Do DOM setup immediately, but keep auxiliary API calls out of the critical
    # first-state request path.
    text = text.replace('if(live)top.appendChild(live);loadAuto();', 'if(live)top.appendChild(live);')
    old = "document.addEventListener('click',e=>{const d=e.target.closest?.('[data-date]');if(d)setTimeout(()=>enhanceCalendarDay(d.dataset.date),30)});loadDisclosureAlerts();loadFlowAlerts();setInterval(loadAuto,12000);setInterval(loadDisclosureAlerts,7000);setInterval(loadFlowAlerts,4000)"
    new = "document.addEventListener('click',e=>{const d=e.target.closest?.('[data-date]');if(d)setTimeout(()=>enhanceCalendarDay(d.dataset.date),30)});setTimeout(()=>{loadAuto();loadDisclosureAlerts();loadFlowAlerts()},1200);setInterval(loadAuto,12000);setInterval(loadDisclosureAlerts,7000);setInterval(loadFlowAlerts,4000)"
    text = text.replace(old, new)
    return text


def _patch_v344(text: str) -> str:
    old = "function init(){separateSmartMoney();bind();buildEventBrowser();syncSession();loadEvents(true);setInterval(syncSession,15000);setInterval(()=>loadEvents(true),120000);document.addEventListener('visibilitychange',()=>{if(!document.hidden){syncSession();loadEvents(true)}})}"
    new = "function init(){separateSmartMoney();bind();buildEventBrowser();setTimeout(syncSession,900);setTimeout(()=>loadEvents(true),1400);setInterval(syncSession,15000);setInterval(()=>loadEvents(true),120000);document.addEventListener('visibilitychange',()=>{if(!document.hidden){syncSession();loadEvents(true)}})}"
    return text.replace(old, new)


def _patch_v364(text: str) -> str:
    # Main state gets first network priority. Condition labels/flow arrive just
    # after first paint instead of competing with /api/state on page entry.
    old = "function changed(){const m=mode();if(m===lastMode)return;lastMode=m;ensure();renderTimes();loadScores();loadFlow();try{renderTrades(STATE||{})}catch(_){}}"
    new = "function changed(){const m=mode();if(m===lastMode)return;lastMode=m;ensure();renderTimes();setTimeout(loadScores,650);setTimeout(loadFlow,1300);try{renderTrades(STATE||{})}catch(_){}}"
    return text.replace(old, new)


def _patch_stock(text: str) -> str:
    if 'GY_FAST_STOCK_V1_' not in text:
        marker = "const flowCanvas=$('investorFlowCanvas'),fctx=flowCanvas.getContext('2d'),ftip=$('investorFlowTooltip');"
        helper = marker + r'''
const __stockCacheKey=tf=>`GY_FAST_STOCK_V1_${MARKET}_${CODE}_${tf}`;
function __stockCacheGet(tf){try{const x=JSON.parse(localStorage.getItem(__stockCacheKey(tf))||'null');return x?.d||null}catch(_){return null}}
function __stockCachePut(tf,d){try{localStorage.setItem(__stockCacheKey(tf),JSON.stringify({ts:Date.now(),d}))}catch(_){}}
'''
        text = text.replace(marker, helper, 1)

    old = "async function loadStock(tf=TF){TF=tf;document.querySelectorAll('[data-tf]').forEach(b=>b.classList.toggle('active',b.dataset.tf===TF));try{const r=await fetch(`/api/v344/stock/${MARKET}/${encodeURIComponent(CODE)}?timeframe=${encodeURIComponent(TF)}&days=60`,{cache:'no-store'});if(!r.ok)throw new Error(`HTTP ${r.status}`);render(await r.json())}catch(e){console.error(e);$('chartStatus').textContent='종목 데이터 연결 오류';drawCandles()}}"
    new = "async function loadStock(tf=TF){TF=tf;document.querySelectorAll('[data-tf]').forEach(b=>b.classList.toggle('active',b.dataset.tf===TF));const cached=__stockCacheGet(TF);if(cached)try{render(cached)}catch(_){}try{const r=await fetch(`/api/v344/stock/${MARKET}/${encodeURIComponent(CODE)}?timeframe=${encodeURIComponent(TF)}&days=60`,{cache:'no-store'});if(!r.ok)throw new Error(`HTTP ${r.status}`);const d=await r.json();render(d);__stockCachePut(TF,d)}catch(e){console.error(e);if(!cached){$('chartStatus').textContent='종목 데이터 연결 오류';drawCandles()}}}"
    return text.replace(old, new)


def apply(ns: dict | None = None) -> bool:
    global _INSTALLED
    if _INSTALLED:
        return True

    _patch_text('static/app.js', _patch_app)
    _patch_text('static/v34.js', _patch_v34)
    _patch_text('static/v344.js', _patch_v344)
    _patch_text('static/v364_main.js', _patch_v364)
    _patch_text('static/stock.js', _patch_stock)

    # Versioned static assets are immutable for a given deploy SHA. Let the
    # browser reuse them instantly on repeat navigation/reload.
    try:
        core = (ns or {}).get('core') if isinstance(ns, dict) else None
        app = getattr(core, 'app', None) if core is not None else None
        if app is not None and not getattr(app.state, '_namuh_static_cache', False):
            app.state._namuh_static_cache = True

            @app.middleware('http')
            async def _namuh_static_cache(request, call_next):
                response = await call_next(request)
                if request.url.path.startswith('/static/') and response.status_code == 200:
                    response.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
                return response
    except Exception as exc:
        print('NAMUH PAGE SPEED middleware error:', str(exc)[:180], flush=True)

    _INSTALLED = True
    print('NAMUH PAGE SPEED active: instant state/stock cache + first-paint request priority + immutable static cache', flush=True)
    return True
