from pathlib import Path

# Keep all previous runtime/static hotfixes first.
import sitecustomize_legacy

ROOT=Path(__file__).resolve().parent
INDEX=ROOT/'static'/'index.html'
TAGS=(
    '<script src="/static/v352.js?v=352"></script>',
    '<script src="/static/v353_searchfix.js?v=353"></script>',
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

import namuh_patch_loader
namuh_patch_loader.install()
