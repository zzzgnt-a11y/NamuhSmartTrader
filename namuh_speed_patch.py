from pathlib import Path
import re
import threading
import time

ROOT = Path(__file__).resolve().parent
_HEALTH_LOCK = threading.RLock()
_HEALTH_CACHE = {"ts": 0.0, "data": None}


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


def _install_health_shield(ns, ttl=10.0):
    core = ns.get('core') if isinstance(ns, dict) else None
    if core is None:
        return False
    old = core.health_payload
    if getattr(old, '_namuh_speed_health_shield', False):
        return True

    def health_payload():
        now = time.monotonic()
        data = _HEALTH_CACHE.get('data')
        if data is not None and now - float(_HEALTH_CACHE.get('ts') or 0.0) < ttl:
            return dict(data)
        with _HEALTH_LOCK:
            now = time.monotonic()
            data = _HEALTH_CACHE.get('data')
            if data is not None and now - float(_HEALTH_CACHE.get('ts') or 0.0) < ttl:
                return dict(data)
            out = dict(old())
            _HEALTH_CACHE['data'] = out
            _HEALTH_CACHE['ts'] = now
            return dict(out)

    health_payload._namuh_speed_health_shield = True
    health_payload._old = old
    core.health_payload = health_payload
    return True


def apply(ns=None):
    # Speed only: do not alter strategy, scoring, UI layout, filters, or calendars.
    shield = _install_health_shield(ns, 10.0)
    # Maximum practical UI polling: stock 1s, time-AI 1s, coin 1s.
    _rewrite('static/app.js', [
        (r'setInterval\(refresh\s*,\s*(?:1000|3000|5000|10000)\)', 'setInterval(refresh,1000)'),
    ])
    _rewrite('static/v364_main.js', [
        (r'setInterval\(loadScores\s*,\s*(?:1000|5000|10000|20000)\)', 'setInterval(loadScores,1000)'),
    ])
    _rewrite('static/coin.js', [
        (r'setInterval\(refresh\s*,\s*(?:1000|3000|5000|10000)\)', 'setInterval(refresh,1000)'),
    ])
    print(f'NAMUH SPEED PATCH active: health10={shield} stock=1s AI=1s coin=1s', flush=True)
