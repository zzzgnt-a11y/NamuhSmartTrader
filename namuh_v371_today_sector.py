from __future__ import annotations

_INSTALLED = False


def _f(v, default=0.0):
    try:
        return float(v)
    except Exception:
        return float(default)


def apply(ns=None):
    global _INSTALLED
    if _INSTALLED:
        return True
    core = ns.get('core') if isinstance(ns, dict) else None
    if core is None:
        return False

    old = core.build_sector_context
    if getattr(old, '_namuh_v371_today_only', False):
        _INSTALLED = True
        return True

    def build_sector_context(market):
        sectors, secmap, stock_strength = old(market)
        if str(market).upper() != 'KR' or not sectors:
            return sectors, secmap, stock_strength

        groups = {}
        for q in list(core.feed.quotes_for('KR').values()):
            try:
                if _f(getattr(q, 'price', 0)) <= 0:
                    continue
                sec = str(core.sector_name(q, 'KR'))
                groups.setdefault(sec, []).append(q)
            except Exception:
                continue

        for x in sectors:
            qs = groups.get(str(x.get('sector') or ''), [])
            fnet = sum(_f(getattr(q, 'foreign_net', 0)) for q in qs)
            inet = sum(_f(getattr(q, 'institution_net', 0)) for q in qs)
            pnet = sum(_f(getattr(q, 'program_net', 0)) for q in qs)
            person = sum(_f(getattr(q, 'person_net', 0)) for q in qs)
            fv = {
                'foreign': sum(_f(getattr(q, 'price', 0)) * max(0.0, _f(getattr(q, 'foreign_net', 0))) for q in qs),
                'institution': sum(_f(getattr(q, 'price', 0)) * max(0.0, _f(getattr(q, 'institution_net', 0))) for q in qs),
                'program': sum(_f(getattr(q, 'price', 0)) * max(0.0, _f(getattr(q, 'program_net', 0))) for q in qs),
                'person_exit': sum(_f(getattr(q, 'price', 0)) * max(0.0, -_f(getattr(q, 'person_net', 0))) for q in qs),
            }
            x['foreign_net'] = fnet
            x['institution_net'] = inet
            x['program_net'] = pnet
            x['person_net'] = person
            x['flow_value'] = fv
            x['flow_source'] = {
                'foreign': 'today_current',
                'institution': 'today_current',
                'program': 'today_current',
                'person_exit': 'today_current',
                'historical_fallback': False,
            }

        keys = ('foreign', 'institution', 'program', 'person_exit')
        totals = {k: sum(max(0.0, _f((x.get('flow_value') or {}).get(k))) for x in sectors) for k in keys}
        comp_total = 0.0
        for x in sectors:
            fv = x.get('flow_value') or {}
            sh = {k: (_f(fv.get(k)) / totals[k] * 100.0 if totals[k] > 0 else 0.0) for k in keys}
            raw = sh['foreign'] * 0.35 + sh['institution'] * 0.35 + sh['program'] * 0.20 + sh['person_exit'] * 0.10
            x['flow_share'] = {**{k: round(v, 1) for k, v in sh.items()}, '_raw': raw}
            comp_total += raw
        for x in sectors:
            sh = x.get('flow_share') or {}
            raw = _f(sh.pop('_raw', 0))
            sh['composite'] = round(raw / comp_total * 100.0, 1) if comp_total > 0 else 0.0
            x['flow_share'] = sh

        sectors.sort(key=lambda x: (_f((x.get('flow_share') or {}).get('composite')), _f(x.get('score'))), reverse=True)
        core._NAMUH_V371_TODAY_SECTOR = {
            'window': 'today_current_session_only',
            'historical_fallback': False,
            'totals': {k: round(v, 2) for k, v in totals.items()},
        }
        return sectors, {str(x.get('sector') or ''): _f(x.get('score')) for x in sectors}, stock_strength

    build_sector_context._namuh_v371_today_only = True
    build_sector_context._old = old
    core.build_sector_context = build_sector_context

    old_health = core.health_payload
    def health():
        d = dict(old_health())
        d['v371'] = {
            'active': True,
            'leading_sector_window': 'today_current_session_only',
            'historical_fallback': False,
            'status': getattr(core, '_NAMUH_V371_TODAY_SECTOR', {}),
        }
        return d
    health._old = old_health
    core.health_payload = health

    _INSTALLED = True
    print('NAMUH V371 active: KR leading-sector flow = today current session only; no 5-day fallback', flush=True)
    return True
