from __future__ import annotations

import re
import threading

_INSTALLED = False

# Broad public activity pages contain ETFs/ETNs as well as ordinary shares.
# The stock scalp detector should discover shares, not let leveraged/index funds
# dominate the newly-expanded universe.
_FUND_PREFIXES = (
    'KODEX','TIGER','RISE','ACE','PLUS','SOL','KOSEF','HANARO','TIMEFOLIO',
    'KBSTAR','ARIRANG','FOCUS','TREX','SMART','QV','TRUE','HANARO','1Q',
)


def _fund_like(name: str) -> bool:
    s = re.sub(r'\s+', ' ', str(name or '')).strip().upper()
    if not s:
        return False
    if ' ETN' in f' {s}' or s.endswith('ETN') or ' ETF' in f' {s}' or s.endswith('ETF'):
        return True
    return any(s.startswith(p) for p in _FUND_PREFIXES)


def _apply_master_meta(core, code: str):
    code = str(code or '').upper().strip()
    if not code:
        return
    try:
        meta = dict((getattr(core.feed, 'kr_master_meta', {}) or {}).get(code) or {})
        q = core.feed.quotes_for('KR').get(code)
        if q is None:
            return
        name = str(meta.get('name') or '').strip()
        sector = str(meta.get('sector') or '').strip()
        if name and name != code:
            q.name = name
        if sector:
            q.sector = sector
    except Exception:
        pass


def apply(ns=None):
    global _INSTALLED
    if _INSTALLED:
        return True
    core = ns.get('core') if isinstance(ns, dict) else None
    if core is None:
        return False

    try:
        import namuh_scalp_sector_final_0908 as final
    except Exception:
        return False

    # 1) Every newly activated quote receives its master name/sector. Previously
    # non-fixed discoveries could appear as raw six-digit codes and generic sectors.
    old_apply_kr = getattr(core.feed, '_apply_kr', None)
    if callable(old_apply_kr) and not getattr(old_apply_kr, '_namuh_discovery_meta_v2', False):
        def apply_kr(code, data):
            out = old_apply_kr(code, data)
            _apply_master_meta(core, code)
            return out
        apply_kr._namuh_discovery_meta_v2 = True
        apply_kr._old = old_apply_kr
        core.feed._apply_kr = apply_kr

    # 2) Keep the broad activity discovery, but filter funds using the already
    # loaded domestic master. Trading/scoring data still comes from official NH.
    old_public = getattr(final, '_public_rank_codes', None)
    if callable(old_public) and not getattr(old_public, '_namuh_stock_only_v2', False):
        def public_rank_codes(core0, limit=60):
            # Ask the original collector for a wider list before filtering so the
            # resulting pool still contains enough ordinary shares.
            raw = list(old_public(core0, max(120, min(190, int(limit or 60) * 3))) or [])
            master = getattr(core0.feed, 'kr_master_meta', {}) or {}
            out = []
            seen = set()
            for code in raw:
                code = str(code or '').upper().strip()
                if len(code) != 6 or not code.isdigit() or code in seen:
                    continue
                meta = dict(master.get(code) or {})
                name = str(meta.get('name') or '').strip()
                if _fund_like(name):
                    continue
                seen.add(code)
                out.append(code)
                if len(out) >= int(limit or 60):
                    break
            return out
        public_rank_codes._namuh_stock_only_v2 = True
        public_rank_codes._old = old_public
        final._public_rank_codes = public_rank_codes

    # 3) Clean any fund quote that slipped into this process before the wrapper
    # was installed. Never touch an open position.
    try:
        held = {str(getattr(p, 'code', '')) for p in core.paper.positions.values()
                if str(getattr(p, 'market', '')).upper() == 'KR'}
    except Exception:
        held = set()
    try:
        for code, q in list(core.feed.quotes_for('KR').items()):
            _apply_master_meta(core, code)
            meta = dict((getattr(core.feed, 'kr_master_meta', {}) or {}).get(str(code)) or {})
            if code not in held and _fund_like(meta.get('name')):
                q.price = 0.0
    except Exception:
        pass

    # Refresh the discovery pool immediately in the background. The normal 45s
    # refresh remains the owner afterwards; this adds no new recurring thread.
    try:
        threading.Thread(target=final._refresh_discovery, args=(core,), daemon=True,
                         name='namuh-stock-only-discovery-refresh').start()
    except Exception:
        pass

    _INSTALLED = True
    print('NAMUH SCALP/SECTOR DIVERSITY V2 active: ordinary-share discovery + master metadata', flush=True)
    return True
