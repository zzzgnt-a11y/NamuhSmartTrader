from pathlib import Path
import re
import threading
import time

ROOT = Path(__file__).resolve().parent
_STATE_LOCK = threading.RLock()
_STATE_CACHE = {}
_STATE_REFRESHING = set()


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


def _install_state_swr(ns):
    """Make /api/state non-blocking for the browser.

    The heavy original state builder still runs, but only in a background
    refresh. Requests get the last completed snapshot immediately. Trading and
    scoring loops are untouched; this changes display delivery only.
    """
    core = ns.get('core') if isinstance(ns, dict) else None
    app = getattr(core, 'app', None) if core is not None else None
    if app is None:
        return False
    try:
        route = next((r for r in app.routes if getattr(r, 'path', None) == '/api/state' and hasattr(r, 'dependant')), None)
        if route is None or getattr(route, '_namuh_state_swr', False):
            return bool(route)
        old = route.dependant.call

        def _key(kwargs):
            market = str(kwargs.get('market') or 'KR').upper()
            return market if market in ('KR', 'US', 'COIN') else 'KR'

        def _refresh(key, kwargs):
            try:
                out = old(**kwargs)
                if isinstance(out, dict):
                    with _STATE_LOCK:
                        _STATE_CACHE[key] = (time.monotonic(), out)
            except Exception as exc:
                print('NAMUH STATE SWR refresh error:', key, str(exc)[:160], flush=True)
            finally:
                with _STATE_LOCK:
                    _STATE_REFRESHING.discard(key)

        def _start_refresh(key, kwargs):
            with _STATE_LOCK:
                if key in _STATE_REFRESHING:
                    return
                _STATE_REFRESHING.add(key)
            threading.Thread(target=_refresh, args=(key, dict(kwargs)), daemon=True).start()

        def state_swr(**kwargs):
            key = _key(kwargs)
            now = time.monotonic()
            with _STATE_LOCK:
                item = _STATE_CACHE.get(key)
            if item is not None:
                age = now - float(item[0])
                if age >= 2.0:
                    _start_refresh(key, kwargs)
                return item[1]

            # A cache miss is rare after startup pre-warm. If it happens, build
            # once synchronously so the API contract is never replaced by a
            # partial/synthetic payload.
            out = old(**kwargs)
            if isinstance(out, dict):
                with _STATE_LOCK:
                    _STATE_CACHE[key] = (time.monotonic(), out)
            return out

        route.dependant.call = state_swr
        route.endpoint = state_swr
        route._namuh_state_swr = True

        # Pre-warm after the server begins booting. Render normally takes longer
        # than this to expose the new instance, so first public paint has a
        # completed snapshot ready instead of paying the full state-build cost.
        def _prewarm():
            time.sleep(2.0)
            for market in ('KR', 'US', 'COIN'):
                with _STATE_LOCK:
                    if market in _STATE_REFRESHING:
                        continue
                    _STATE_REFRESHING.add(market)
                _refresh(market, {'market': market})

        threading.Thread(target=_prewarm, daemon=True).start()
        return True
    except Exception as exc:
        print('NAMUH STATE SWR install error:', str(exc)[:180], flush=True)
        return False


def apply(ns=None):
    # Speed only: do not alter strategy, scoring, UI layout, filters, or calendars.
    # /api/state uses stale-while-revalidate so a slow scanner can no longer
    # freeze page loads. Later v372 normalizes visible polling to 5 seconds.
    swr = _install_state_swr(ns)
    _rewrite('static/app.js', [
        (r'setInterval\(refresh\s*,\s*(?:1000|3000|5000|10000)\)', 'setInterval(refresh,1000)'),
    ])
    _rewrite('static/v364_main.js', [
        (r'setInterval\(loadScores\s*,\s*(?:1000|5000|10000|20000)\)', 'setInterval(loadScores,1000)'),
    ])
    _rewrite('static/coin.js', [
        (r'setInterval\(refresh\s*,\s*(?:1000|3000|5000|10000)\)', 'setInterval(refresh,1000)'),
    ])
    print(f'NAMUH SPEED PATCH active: state_swr={swr} stock=1s AI=1s coin=1s', flush=True)
