from __future__ import annotations

import time
from collections import deque

_INSTALLED = False


def _present(obj, keys):
    for k in keys:
        if k in obj and obj.get(k) not in (None, ''):
            return k, obj.get(k)
    return None, None


def apply(ns=None):
    global _INSTALLED
    if _INSTALLED:
        return True
    core = ns.get('core') if isinstance(ns, dict) else None
    if core is None:
        return False
    feed = core.feed
    from nhfeed import walk, num, normalize_date, pick

    old_inv = getattr(feed, '_apply_investor', None)

    def merged_investor(code, data):
        parsed = {}
        for o in walk(data):
            if not isinstance(o, dict):
                continue
            # NH currentInvestor exposes `frgn_ntby_qty` and `invest` together
            # with different values. `invest` is NOT an alias for foreign flow;
            # only the explicit foreign field may populate the foreign bucket.
            fk, fv = _present(o, ('frgn_ntby_qty', 'foreign'))
            ik, iv = _present(o, ('orgn_ntby_qty', 'gigwan'))
            pk, pv = _present(o, ('prsn_ntby_qty', 'person'))
            gk, gv = _present(o, ('prgm_ntby_qty', 'pgtr_ntby_qty', 'program'))
            if not any((fk, ik, pk, gk)):
                continue
            d = normalize_date(
                o.get('bsop_date1') or o.get('bsop_date2') or o.get('bsop_date')
                or o.get('stck_bsop_date') or o.get('trade_date') or o.get('date')
                or o.get('xymd') or o.get('trd_dd')
            )
            if not d:
                continue
            row = parsed.setdefault(d, {'date': d, 'foreign': None, 'institution': None, 'person': None, 'program': None})
            if fk: row['foreign'] = num(fv)
            if ik: row['institution'] = num(iv)
            if pk: row['person'] = num(pv)
            if gk: row['program'] = num(gv)

        if not parsed:
            if callable(old_inv):
                return old_inv(code, data)
            return None

        ordered = [parsed[k] for k in sorted(parsed)][-14:]
        latest = ordered[-1]
        q = feed.q('KR', code)
        q.update_flow(
            latest['foreign'] if latest['foreign'] is not None else None,
            latest['institution'] if latest['institution'] is not None else None,
            latest['program'] if latest['program'] is not None else None,
        )
        if latest['person'] is not None:
            q.person_net = latest['person']
        q.investor_daily = deque([
            {
                'date': r['date'],
                'foreign': 0.0 if r['foreign'] is None else r['foreign'],
                'institution': 0.0 if r['institution'] is None else r['institution'],
                'person': 0.0 if r['person'] is None else r['person'],
                'program': 0.0 if r['program'] is None else r['program'],
            } for r in ordered
        ], maxlen=14)
        q.investor_asof = latest['date']
        q.investor_data_ready = True
        q.investor_updated_at = time.time()
        return True

    merged_investor._namuh_merge_final = True
    merged_investor._old = old_inv
    feed._apply_investor = merged_investor

    # currentPrice fallback may update only fields that are explicitly present.
    # Never reinterpret `invest` as foreign flow.
    old_kr = getattr(feed, '_apply_kr', None)
    if callable(old_kr) and not getattr(old_kr, '_namuh_investor_fallback', False):
        def apply_kr(code, data):
            old_kr(code, data)
            q = feed.q('KR', code)
            objs = [o for o in walk(data) if isinstance(o, dict)]
            found_f = any(('frgn_ntby_qty' in o and o.get('frgn_ntby_qty') not in (None, '')) or ('foreign' in o and o.get('foreign') not in (None, '')) for o in objs)
            found_p = any(('pgtr_ntby_qty' in o and o.get('pgtr_ntby_qty') not in (None, '')) or ('prgm_ntby_qty' in o and o.get('prgm_ntby_qty') not in (None, '')) or ('program' in o and o.get('program') not in (None, '')) for o in objs)
            if found_f or found_p:
                f = pick(data, ('frgn_ntby_qty', 'foreign')) if found_f else None
                p = pick(data, ('pgtr_ntby_qty', 'prgm_ntby_qty', 'program')) if found_p else None
                q.update_flow(foreign=f, program=p)
        apply_kr._namuh_investor_fallback = True
        feed._apply_kr = apply_kr

    _INSTALLED = True
    print('NAMUH INVESTOR MERGE FINAL active: explicit foreign field + merged investor rows', flush=True)
    return True
