from __future__ import annotations

import os
import re
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
_INSTALLED = False


def _f(v, default=0.0):
    try:
        return float(v)
    except Exception:
        return float(default)


def _date(v):
    s = ''.join(ch for ch in str(v or '') if ch.isdigit())
    return s[:8] if len(s) >= 8 else ''


def _completed5(q, key, today):
    vals = []
    for r in list(getattr(q, 'investor_daily', []) or []):
        if not isinstance(r, dict):
            continue
        d = _date(r.get('date'))
        if not d or d >= today:
            continue
        vals.append((d, _f(r.get(key))))
    vals.sort(key=lambda x: x[0])
    use = [v for _, v in vals[-5:]]
    return (sum(use), len(use)) if use else (0.0, 0)


def _effective_institution(q, today):
    current = _f(getattr(q, 'institution_net', 0))
    if current != 0:
        return current, False, 0
    hist, days = _completed5(q, 'institution', today)
    if days and hist != 0:
        return hist, True, days
    return current, False, days


def _install_institution_sector_fix(core):
    old = core.build_sector_context
    if getattr(old, '_namuh_v370_institution', False):
        return

    def build_sector_context(market):
        sectors, secmap, stock_strength = old(market)
        if str(market).upper() != 'KR' or not sectors:
            return sectors, secmap, stock_strength

        try:
            today = core.datetime.now(core.KST).strftime('%Y%m%d')
        except Exception:
            today = time.strftime('%Y%m%d')

        groups = {}
        for q in list(core.feed.quotes_for('KR').values()):
            try:
                if _f(getattr(q, 'price', 0)) <= 0:
                    continue
                sec = str(core.sector_name(q, 'KR'))
                groups.setdefault(sec, []).append(q)
            except Exception:
                continue

        fallback_members = 0
        fallback_sectors = 0
        for x in sectors:
            qs = groups.get(str(x.get('sector') or ''), [])
            if not qs:
                continue
            eff_i = 0.0
            ival = 0.0
            used = 0
            days = 0
            for q in qs:
                iv, fb, d = _effective_institution(q, today)
                eff_i += iv
                ival += _f(getattr(q, 'price', 0)) * max(0.0, iv)
                used += 1 if fb else 0
                days = max(days, d)
            fv = dict(x.get('flow_value') or {})
            fv['institution'] = ival
            x['flow_value'] = fv
            x['institution_net'] = eff_i
            src = dict(x.get('flow_source') or {})
            src['institution'] = 'recent5_completed' if used else 'current'
            src['institution_fallback_members'] = used
            src['institution_history_days'] = days
            x['flow_source'] = src
            if used:
                fallback_sectors += 1
                fallback_members += used

        keys = ('foreign', 'institution', 'program', 'person_exit')
        totals = {k: sum(max(0.0, _f((x.get('flow_value') or {}).get(k))) for x in sectors) for k in keys}
        comp_sum = 0.0
        for x in sectors:
            fv = x.get('flow_value') or {}
            sh = {k: (_f(fv.get(k)) / totals[k] * 100.0 if totals[k] > 0 else 0.0) for k in keys}
            raw = sh['foreign'] * 0.35 + sh['institution'] * 0.35 + sh['program'] * 0.20 + sh['person_exit'] * 0.10
            x['flow_share'] = {**{k: round(v, 1) for k, v in sh.items()}, '_raw': raw}
            comp_sum += raw
        for x in sectors:
            sh = x.get('flow_share') or {}
            raw = _f(sh.pop('_raw', 0))
            sh['composite'] = round(raw / comp_sum * 100.0, 1) if comp_sum > 0 else 0.0
            x['flow_share'] = sh
        sectors.sort(key=lambda x: (_f((x.get('flow_share') or {}).get('composite')), _f(x.get('score'))), reverse=True)
        try:
            core._NAMUH_V370_INSTITUTION = {
                'fallback_sectors': fallback_sectors,
                'fallback_members': fallback_members,
                'institution_total_value': round(totals['institution'], 2),
            }
        except Exception:
            pass
        return sectors, {str(x.get('sector') or ''): _f(x.get('score')) for x in sectors}, stock_strength

    build_sector_context._namuh_v370_institution = True
    build_sector_context._old = old
    core.build_sector_context = build_sector_context


def _install_score_only_order(core):
    old_candidate = core.candidate
    if not getattr(old_candidate, '_namuh_v370_score_only', False):
        def candidate(*args, **kwargs):
            out = old_candidate(*args, **kwargs)
            if isinstance(out, dict) and not bool(kwargs.get('smart', False)):
                out['priority_score'] = _f(out.get('score'))
                out['reasons'] = [r for r in list(out.get('reasons') or []) if '대장주 우선' not in str(r)]
            return out
        candidate._namuh_v370_score_only = True
        candidate._old = old_candidate
        core.candidate = candidate

    old_rebuild = core.rebuild_cache
    if getattr(old_rebuild, '_namuh_v370_score_only', False):
        return

    def rebuild_cache(market, now=None):
        scalp, smart = old_rebuild(market, now)
        scalp = list(scalp or [])
        scalp.sort(key=lambda x: _f(x.get('score')), reverse=True)
        for x in scalp:
            if isinstance(x, dict):
                x['priority_score'] = _f(x.get('score'))
                x['reasons'] = [r for r in list(x.get('reasons') or []) if '대장주 우선' not in str(r)]
        try:
            with core.cache_lock:
                c = dict(core.CACHE.get(str(market).upper()) or {})
                c['scalp'] = scalp[:50]
                core.CACHE[str(market).upper()] = c
        except Exception:
            pass
        return scalp, smart

    rebuild_cache._namuh_v370_score_only = True
    rebuild_cache._old = old_rebuild
    core.rebuild_cache = rebuild_cache


def _rewrite_static(build):
    for rel in ('static/index.html', 'static/coin.html'):
        p = ROOT / rel
        if not p.exists():
            continue
        text = p.read_text(encoding='utf-8')
        text = re.sub(r'\s*<script\s+src=["\']/static/v368_top5_runtime\.js(?:\?[^"\']*)?["\']\s*></script>\s*', '\n', text, flags=re.I)
        text = re.sub(r'(["\']/static/[^"\'?]+\.(?:js|css))\?v=[^"\']*', lambda m: f"{m.group(1)}?v={build}", text)
        tag = f'  <script src="/static/v370_userfix.js?v={build}"></script>'
        text = re.sub(r'\s*<script\s+src=["\']/static/v370_userfix\.js(?:\?[^"\']*)?["\']\s*></script>\s*', '\n', text, flags=re.I)
        text = text.replace('</body>', f'{tag}\n</body>')
        p.write_text(text, encoding='utf-8')

    for rel in ('static/stock.html', 'static/index-detail.html', 'static/coin-detail.html'):
        p = ROOT / rel
        if not p.exists():
            continue
        text = p.read_text(encoding='utf-8')
        text = re.sub(r'(["\']/static/[^"\'?]+\.(?:js|css))\?v=[^"\']*', lambda m: f"{m.group(1)}?v={build}", text)
        p.write_text(text, encoding='utf-8')

    p = ROOT / 'static/app.js'
    if p.exists():
        text = p.read_text(encoding='utf-8')
        text = text.replace(' · 대장주 우선 · 기술 · 공시', ' · 기술 · 공시')
        text = text.replace('${x.is_sector_leader&&!smart?" · 섹터 대장주 우선":""}', '')
        text = text.replace('||(Number(b.priority_score||0)-Number(a.priority_score||0))', '')
        p.write_text(text, encoding='utf-8')


def _install_health(core):
    old = core.health_payload
    if getattr(old, '_namuh_v370', False):
        return

    def health():
        d = dict(old())
        d['v370'] = {
            'active': True,
            'score_order': 'final_score_only',
            'leader_priority': False,
            'institution_sector_fallback': True,
            'today_trade_history_only': True,
            'calendar_ledger_persistent': True,
            'calendar_ui_unified': True,
            'static_cache_bust_per_deploy': True,
            'institution': getattr(core, '_NAMUH_V370_INSTITUTION', {}),
        }
        return d

    health._namuh_v370 = True
    health._old = old
    core.health_payload = health


def apply(ns=None):
    global _INSTALLED
    if _INSTALLED:
        return True
    core = ns.get('core') if isinstance(ns, dict) else None
    if core is None:
        return False
    _INSTALLED = True
    _install_institution_sector_fix(core)
    _install_score_only_order(core)
    build = (os.getenv('RENDER_GIT_COMMIT') or os.getenv('GY_BUILD_ID') or str(int(time.time())))[:12]
    _rewrite_static(build)
    _install_health(core)
    print('NAMUH V370 active: site cache-bust + institution sector + unified calendars + today trades + pnl + score-only order', flush=True)
    return True
