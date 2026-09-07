from pathlib import Path
import sys

# Keep all previous runtime/static hotfixes first.
import sitecustomize_legacy

ROOT=Path(__file__).resolve().parent
INDEX=ROOT/'static'/'index.html'
TAGS=(
    '<script src="/static/v352.js?v=352"></script>',
    '<script src="/static/v353_searchfix.js?v=353"></script>',
    '<script src="/static/v354_scoreui.js?v=354"></script>',
)
try:
    text=INDEX.read_text(encoding='utf-8')
    changed=False
    for tag in TAGS:
        if tag not in text:
            text=text.replace('</body>',f'  {tag}\n</body>')
            changed=True
    if changed:
        INDEX.write_text(text,encoding='utf-8')
except Exception:
    pass

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
            except Exception as exc:
                print('LATE RUNTIME PATCH ERROR:',exc,flush=True)
            return _orig_uvicorn_run(*args,**kwargs)
        uvicorn.run=_run_with_coin_patch
except Exception:
    pass
