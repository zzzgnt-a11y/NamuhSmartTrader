from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent


def _rewrite(rel, transforms):
    p = ROOT / rel
    if not p.exists():
        return False
    text = p.read_text(encoding='utf-8')
    before = text
    for pattern, repl in transforms:
        text = re.sub(pattern, repl, text)
    if text != before:
        p.write_text(text, encoding='utf-8')
        return True
    return False


def apply(ns=None):
    # Speed only: do not alter strategy, scoring, UI layout, filters, or calendars.
    # Stock state: 3s, time-AI score refresh: 5s, coin state: 3s.
    _rewrite('static/app.js', [
        (r'setInterval\(refresh\s*,\s*(?:5000|10000)\)', 'setInterval(refresh,3000)'),
    ])
    _rewrite('static/v364_main.js', [
        (r'setInterval\(loadScores\s*,\s*(?:10000|20000)\)', 'setInterval(loadScores,5000)'),
    ])
    _rewrite('static/coin.js', [
        (r'setInterval\(refresh\s*,\s*(?:5000|10000)\)', 'setInterval(refresh,3000)'),
    ])
    print('NAMUH SPEED PATCH active: stock=3s AI=5s coin=3s', flush=True)
