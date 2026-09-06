from pathlib import Path

# Keep all previous runtime/static hotfixes first.
import sitecustomize_legacy

ROOT=Path(__file__).resolve().parent
INDEX=ROOT/'static'/'index.html'
TAG='<script src="/static/v352.js?v=352"></script>'
try:
    text=INDEX.read_text(encoding='utf-8')
    if TAG not in text:
        text=text.replace('</body>',f'  {TAG}\n</body>')
        INDEX.write_text(text,encoding='utf-8')
except Exception:
    pass

import namuh_patch_loader
namuh_patch_loader.install()
