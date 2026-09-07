from pathlib import Path
import os
import re
import sys

# Keep all previous runtime/static hotfixes first.
import sitecustomize_legacy

ROOT=Path(__file__).resolve().parent
INDEX=ROOT/'static'/'index.html'
ASSET_VERSION=(os.getenv('RENDER_GIT_COMMIT') or os.getenv('GY_BUILD_ID') or str(int(__import__('time').time())))[:12]
SCRIPT_NAMES=('v352.js','v353_searchfix.js','v354_scoreui.js')

# Make the browser load exactly one fresh copy of each late UI owner after every
# Render deploy. Fixed ?v=352/354 tags were leaving stale JS in mobile/WebView.
try:
    text=INDEX.read_text(encoding='utf-8')
    for name in SCRIPT_NAMES:
        text=re.sub(
            rf'\s*<script\s+src=["\']/static/{re.escape(name)}(?:\?[^"\']*)?["\']\s*></script>\s*',
            '\n',text,flags=re.I,
        )
    tags='\n'.join(f'  <script src="/static/{name}?v={ASSET_VERSION}"></script>' for name in SCRIPT_NAMES)
    text=text.replace('</body>',f'{tags}\n</body>')
    INDEX.write_text(text,encoding='utf-8')
except Exception as exc:
    print('NAMUH UI TAG PATCH ERROR:',exc,flush=True)

# Align old display helpers with the current KR recipe. This is presentation
# only; trading logic is owned by the runtime patches below.
try:
    p=ROOT/'static'/'v352.js'
    text=p.read_text(encoding='utf-8')
    text=text.replace('전체 ${rows.length}종목 · 40 실시간 + 60 일봉→분봉 · 72점 이상 ${ready}종목',
                      '전체 ${rows.length}종목 · 레시피 80 + 기술 20 · 72점 이상 ${ready}종목')
    old="?[['현재가',money(x.price,m)],['체결강도',ex==null?'—':Number(ex).toFixed(1)],['일봉',ds==null?'—':Number(ds).toFixed(0)],['분봉',ms==null?'—':Number(ms).toFixed(0)],['레시피',recipe==null?'—':Number(recipe).toFixed(0)]]"
    new="?[['현재가',money(x.price,m)],['일봉',Number(comp.daily20||0).toFixed(0)+'/20'],['거래량',Number(comp.volume15||0).toFixed(0)+'/15'],['체결강도',(ex==null?'—':Number(ex).toFixed(1))+' · '+Number(comp.execution20||0).toFixed(0)+'/20'],['기술',Number(comp.technical20||0).toFixed(0)+'/20']]"
    text=text.replace(old,new)
    p.write_text(text,encoding='utf-8')
except Exception as exc:
    print('NAMUH V352 UI PATCH ERROR:',exc,flush=True)

try:
    p=ROOT/'static'/'v354_scoreui.js'
    text=p.read_text(encoding='utf-8')
    text=text.replace('전체 ${n}종목 · 1차 50 + 기술 30 + 보조 20 · 72점 이상 ${ready}종목',
                      '전체 ${n}종목 · 레시피 80 + 기술 20 · 72점 이상 ${ready}종목')
    text=text.replace("if(s)s.textContent='50/30/20';","if(s)s.textContent='80/20';")
    text=text.replace("if(b)b.textContent=`${Number(c.stage50||0).toFixed(0)}/${Number(c.stage30||0).toFixed(0)}/${Number(c.stage20||0).toFixed(0)}`;",
                      "if(b)b.textContent=`${Number(c.recipe80||x.recipe_score||0).toFixed(0)}/${Number(c.technical20||x.technical_score||0).toFixed(0)}`;")
    p.write_text(text,encoding='utf-8')
except Exception as exc:
    print('NAMUH V354 UI PATCH ERROR:',exc,flush=True)

# Coin TECH100 UI hotfix. Runtime v34 may append its own scripts later; this
# script is idempotent and keeps the displayed model aligned with the engine.
for rel in ('static/coin.html','static/coin-detail.html'):
    try:
        p=ROOT/rel
        text=p.read_text(encoding='utf-8')
        tag='<script src="/static/coin-tech100.js?v=100"></script>'
        if tag not in text:
            text=text.replace('</body>',f'  {tag}\n</body>')
            p.write_text(text,encoding='utf-8')
    except Exception:
        pass

import namuh_patch_loader
namuh_patch_loader.install()

# Render starts with `python runtime_server_v34.py`, so that file is __main__.
# Patch at the last possible moment: runtime_server_v34 has finished defining
# its final stock/coin trade layers, but uvicorn has not started lifespan yet.
try:
    import uvicorn
    _orig_uvicorn_run=uvicorn.run
    if not getattr(uvicorn,'_NAMUH_TECH100_WRAPPED',False):
        uvicorn._NAMUH_TECH100_WRAPPED=True
        def _run_with_coin_patch(*args,**kwargs):
            try:
                main=sys.modules.get('__main__')
                ns=getattr(main,'__dict__',{}) if main else {}
                if ns.get('core') is not None and callable(ns.get('_coin_technical_from_bars')):
                    import coin_tech100_patch
                    coin_tech100_patch.apply(ns)
                if ns.get('core') is not None:
                    import namuh_recipe8020_patch
                    namuh_recipe8020_patch.apply(ns)
                    import namuh_execution_exit_patch
                    namuh_execution_exit_patch.apply(ns)
                    # Absolute final KR scalp owner: no legacy signal gate is
                    # consulted after this patch is applied.
                    import namuh_entry_gate_fix
                    namuh_entry_gate_fix.apply(ns)
            except Exception as exc:
                print('LATE RUNTIME PATCH ERROR:',exc,flush=True)
            return _orig_uvicorn_run(*args,**kwargs)
        uvicorn.run=_run_with_coin_patch
except Exception:
    pass
