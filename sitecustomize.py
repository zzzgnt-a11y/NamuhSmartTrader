from pathlib import Path
import os
import re
import sys

# Keep all previous runtime/static hotfixes first.
import sitecustomize_legacy

ROOT=Path(__file__).resolve().parent
INDEX=ROOT/'static'/'index.html'
ASSET_VERSION=(os.getenv('RENDER_GIT_COMMIT') or os.getenv('GY_BUILD_ID') or str(int(__import__('time').time())))[:12]
SCRIPT_NAMES=('v352.js','v353_searchfix.js','v355_unified_ui.js','v356_strategy_ui.js')

# One fresh copy of each late UI owner. v354 is intentionally removed because
# its old 50/30/20 timer could overwrite the active strategy display.
try:
    text=INDEX.read_text(encoding='utf-8')
    for name in ('v352.js','v353_searchfix.js','v354_scoreui.js','v355_unified_ui.js','v356_strategy_ui.js'):
        text=re.sub(rf'\s*<script\s+src=["\']/static/{re.escape(name)}(?:\?[^"\']*)?["\']\s*></script>\s*','\n',text,flags=re.I)
    tags='\n'.join(f'  <script src="/static/{name}?v={ASSET_VERSION}"></script>' for name in SCRIPT_NAMES)
    text=text.replace('</body>',f'{tags}\n</body>')
    INDEX.write_text(text,encoding='utf-8')
except Exception as exc:
    print('NAMUH UI TAG PATCH ERROR:',exc,flush=True)

# Remove legacy title/caption ownership so section 3 no longer flips wording.
try:
    p=ROOT/'static'/'v352.js';text=p.read_text(encoding='utf-8')
    text=text.replace("if(title)title.textContent=m==='US'?'미장 전체 종목 AI 점수':'국장 전체 종목 AI 점수';",
                      "if(title)title.textContent=m==='US'?'미장 단타 탐지':'국장 단타 탐지 · 조건1/2/3';")
    text=text.replace('전체 ${rows.length}종목 · 40 실시간 + 60 일봉→분봉 · 72점 이상 ${ready}종목',
                      '전체 ${rows.length}종목 · 조건1/조건2/조건3 · 실시간 감시')
    text=text.replace("if(col)col.textContent=`전체 AI 점수 · ${rows.length}종목`;",
                      "if(col)col.textContent=`단타 조건 후보 · ${rows.length}종목`;")
    p.write_text(text,encoding='utf-8')
except Exception as exc:print('NAMUH V352 UI PATCH ERROR:',exc,flush=True)

# Stock account is now 4M KRW.
try:
    p=ROOT/'static'/'app.js';text=p.read_text(encoding='utf-8')
    text=text.replace('amount>1000000','amount>4000000')
    text=text.replace('amount>2000000','amount>4000000')
    text=text.replace('0~1,000,000원 범위','0~4,000,000원 범위')
    text=text.replace('0~2,000,000원 범위','0~4,000,000원 범위')
    p.write_text(text,encoding='utf-8')
except Exception as exc:print('NAMUH STOCK BUDGET UI PATCH ERROR:',exc,flush=True)

# Coin UI owner: no news/disclosure/sector/program/1m gate; technical weight 45.
for rel in ('static/coin.html','static/coin-detail.html'):
    try:
        p=ROOT/rel;text=p.read_text(encoding='utf-8')
        for name in ('coin-tech100.js','coin-recipe100.js'):
            text=re.sub(rf'\s*<script\s+src=["\']/static/{re.escape(name)}(?:\?[^"\']*)?["\']\s*></script>\s*','\n',text,flags=re.I)
        tag=f'<script src="/static/coin-recipe100.js?v={ASSET_VERSION}"></script>'
        text=text.replace('</body>',f'  {tag}\n</body>');p.write_text(text,encoding='utf-8')
    except Exception as exc:print('NAMUH COIN UI TAG PATCH ERROR:',exc,flush=True)

import namuh_patch_loader
namuh_patch_loader.install()

# Final runtime owners are installed before FastAPI lifespan starts.
try:
    import uvicorn
    _orig_uvicorn_run=uvicorn.run
    if not getattr(uvicorn,'_NAMUH_TECH100_WRAPPED',False):
        uvicorn._NAMUH_TECH100_WRAPPED=True
        def _run_with_coin_patch(*args,**kwargs):
            try:
                main=sys.modules.get('__main__');ns=getattr(main,'__dict__',{}) if main else {}
                if ns.get('core') is not None and callable(ns.get('_coin_technical_from_bars')):
                    import coin_tech100_patch;coin_tech100_patch.apply(ns)
                if ns.get('core') is not None:
                    import namuh_recipe8020_patch;namuh_recipe8020_patch.apply(ns)
                    import namuh_execution_exit_patch;namuh_execution_exit_patch.apply(ns)
                    import namuh_entry_gate_fix;namuh_entry_gate_fix.apply(ns)
                    import namuh_crossmarket_patch;namuh_crossmarket_patch.apply(ns)
                    import namuh_stock_asset_patch;namuh_stock_asset_patch.apply(ns)
                    # Must be last: owns KR condition1/2/3 entry/exit and final event/sector scoring.
                    import namuh_strategy123_patch;namuh_strategy123_patch.apply(ns)
            except Exception as exc:
                print('LATE RUNTIME PATCH ERROR:',exc,flush=True)
            return _orig_uvicorn_run(*args,**kwargs)
        uvicorn.run=_run_with_coin_patch
except Exception:
    pass
