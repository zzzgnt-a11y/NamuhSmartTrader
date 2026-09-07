from __future__ import annotations

import inspect
import time


def _f(v, default=0.0):
    try:
        return float(v)
    except Exception:
        return float(default)


def _pick(row, keys):
    if not isinstance(row, dict):
        return 0.0
    for k in keys:
        try:
            v = float(str(row.get(k) or 0).replace(',', '').replace('+', '').strip())
        except Exception:
            v = 0.0
        if v > 0:
            return v
    return 0.0


def apply(ns):
    core = ns.get('core') if isinstance(ns, dict) else None
    if core is None or getattr(core, '_NAMUH_C3_SYNC_PRICE_FIX', False):
        return False
    core._NAMUH_C3_SYNC_PRICE_FIX = True
    old_q = core.feed.q

    def q(market, code):
        obj = old_q(market, code)
        if str(market or '').upper() != 'KR' or _f(getattr(obj, 'price', 0)) > 0:
            return obj
        # Isolated to the final Condition3 lower-band candidate resolver only.
        fr = inspect.currentframe().f_back
        if fr is None or fr.f_code.co_name != '_c3_rows' or fr.f_globals.get('__name__') != 'namuh_conditions_final_patch':
            return obj
        try:
            with core.MINUTE_SYNC_LOCK:
                row = dict((core.MINUTE_SYNC.get('rows') or {}).get(str(code).upper()) or {})
        except Exception:
            row = {}
        px = _pick(row, ('price','current_price','close','stck_prpr','now_price'))
        if px <= 0:
            return obj
        try:
            meta = (getattr(core.feed, 'kr_master_meta', {}) or {}).get(str(code), {}) or {}
            obj.name = str(row.get('name') or meta.get('name') or getattr(obj, 'name', '') or code)
            obj.sector = str(row.get('sector') or meta.get('sector') or getattr(obj, 'sector', '') or '')
            obj.mark(px, _f(getattr(obj, 'volume', 0)), time.time())
        except Exception:
            pass
        return obj

    core.feed.q = q
    print('NAMUH C3 sync-price bridge active: only final _c3_rows', flush=True)
    return True
