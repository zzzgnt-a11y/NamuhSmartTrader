from pathlib import Path
import os
import re
import sys

# Keep all previous runtime/static hotfixes first.
import sitecustomize_legacy

ROOT=Path(__file__).resolve().parent
INDEX=ROOT/'static'/'index.html'
ASSET_VERSION=(os.getenv('RENDER_GIT_COMMIT') or os.getenv('GY_BUILD_ID') or str(int(__import__('time').time())))[:12]

# v364 is the only late main-page UI owner. Remove every old owner before
# injecting it so server startup can never revive sub-second render loops.
OLD_MAIN_SCRIPTS=(
    'v352.js','v353_searchfix.js','v354_scoreui.js','v355_unified_ui.js',
    'v356_strategy_ui.js','v357_ui_restore.js','v360_final.js','v361_user15.js',
    'v362_main.js','v363_main.js','v364_main.js',
)
try:
    text=INDEX.read_text(encoding='utf-8')
    for name in OLD_MAIN_SCRIPTS:
        text=re.sub(rf'\s*<script\s+src=["\']/static/{re.escape(name)}(?:\?[^"\']*)?["\']\s*></script>\s*','\n',text,flags=re.I)
    tag=f'  <script src="/static/v364_main.js?v={ASSET_VERSION}"></script>'
    text=text.replace('</body>',f'{tag}\n</body>')
    text=re.sub(
        r'(/static/[^"\'?]+\.(?:js|css))(?:\?v=[^"\']*)?',
        lambda m:f'{m.group(1)}?v={ASSET_VERSION}',
        text,
        flags=re.I,
    )
    INDEX.write_text(text,encoding='utf-8')
except Exception as exc:
    print('NAMUH UI TAG PATCH ERROR:',exc,flush=True)

# Stock account is 4M KRW and the base page refresh is deliberately slower.
try:
    p=ROOT/'static'/'app.js';text=p.read_text(encoding='utf-8')
    text=text.replace('amount>1000000','amount>4000000')
    text=text.replace('amount>2000000','amount>4000000')
    text=text.replace('0~1,000,000원 범위','0~4,000,000원 범위')
    text=text.replace('0~2,000,000원 범위','0~4,000,000원 범위')
    text=text.replace('setInterval(refresh,5000)','setInterval(refresh,10000)')
    p.write_text(text,encoding='utf-8')
except Exception as exc:print('NAMUH STOCK BUDGET/POLL UI PATCH ERROR:',exc,flush=True)

# Reduce auxiliary main-page polling and disable the legacy calendar detail
# request that ignored the selected KR/US market and could re-mix trades.
try:
    p=ROOT/'static'/'v34.js';text=p.read_text(encoding='utf-8')
    text=text.replace('setInterval(loadAuto,12000)','setInterval(loadAuto,30000)')
    text=text.replace('setInterval(loadDisclosureAlerts,7000)','setInterval(loadDisclosureAlerts,30000)')
    text=text.replace('setInterval(loadFlowAlerts,4000)','setInterval(loadFlowAlerts,15000)')
    text=text.replace('async function enhanceCalendarDay(date){if(!date)return;',
                      'async function enhanceCalendarDay(date){return; if(!date)return;')
    p.write_text(text,encoding='utf-8')
except Exception as exc:print('NAMUH V34 POLL/CALENDAR PATCH ERROR:',exc,flush=True)

# Keep the disclosure list, but remove unrequested chart disclosure markers.
try:
    p=ROOT/'static'/'stock-fix.js'
    if p.exists():
        text=p.read_text(encoding='utf-8')
        text=text.replace('function drawDisclosureOverlay(){\n const ov=', 'function drawDisclosureOverlay(){return;\n const ov=')
        p.write_text(text,encoding='utf-8')
    p=ROOT/'static'/'v346.css'
    text=p.read_text(encoding='utf-8')
    rule='#v348ChartEvents{display:none!important}'
    if rule not in text:
        text += '\n/* Stock candle chart: disclosure markers intentionally disabled. */\n'+rule+'\n'
        p.write_text(text,encoding='utf-8')
except Exception as exc:print('NAMUH STOCK DISCLOSURE MARKER PATCH ERROR:',exc,flush=True)

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
                    import minute_bar_persistence
                    minute_bar_persistence.install(ns['core'])
                    import namuh_recipe8020_patch;namuh_recipe8020_patch.apply(ns)
                    import namuh_execution_exit_patch;namuh_execution_exit_patch.apply(ns)
                    import namuh_entry_gate_fix;namuh_entry_gate_fix.apply(ns)
                    import namuh_crossmarket_patch;namuh_crossmarket_patch.apply(ns)
                    import namuh_stock_asset_patch;namuh_stock_asset_patch.apply(ns)
                    import namuh_strategy123_patch;namuh_strategy123_patch.apply(ns)
                    import namuh_strategy23_fix;namuh_strategy23_fix.apply(ns)
                    import namuh_c2_window_patch;namuh_c2_window_patch.apply(ns)
                    import namuh_condition_threshold_patch;namuh_condition_threshold_patch.apply(ns)
                    import v363_market_flow_patch;v363_market_flow_patch.apply(ns)
            except Exception as exc:
                print('LATE RUNTIME PATCH ERROR:',exc,flush=True)
            return _orig_uvicorn_run(*args,**kwargs)
        uvicorn.run=_run_with_coin_patch
except Exception:
    pass
