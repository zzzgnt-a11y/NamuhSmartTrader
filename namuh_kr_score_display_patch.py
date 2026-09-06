from __future__ import annotations

from engine import execution_gate as _execution_gate


def _clamp(v, lo=0.0, hi=100.0):
    try:
        x = float(v or 0)
    except Exception:
        x = 0.0
    return max(lo, min(hi, x))


def apply(m):
    if getattr(m, '_NAMUH_KR_SCORE_DISPLAY_FIX', False):
        return
    m._NAMUH_KR_SCORE_DISPLAY_FIX = True

    old_candidate = m.candidate

    def candidate(q, market, smart=False, secmap=None, stockmap=None,
                  leadermap=None, sector_rankmap=None, now=None):
        out = old_candidate(q, market, smart, secmap, stockmap,
                            leadermap, sector_rankmap, now)
        market2 = str(market or '').upper()
        if smart or market2 != 'KR' or not isinstance(out, dict):
            return out

        try:
            execution_ok, execution_reason = _execution_gate(q)
        except Exception:
            execution_ok, execution_reason = False, '체결강도 확인 대기'

        blocked = bool(getattr(q, 'event_blocked', False))
        try:
            blocked = blocked or any(bool(x.get('blocked')) for x in list(getattr(q, 'events', []) or []) if isinstance(x, dict))
        except Exception:
            pass

        components = dict(out.get('score_components') or {})
        context40 = _clamp(components.get('context40'), 0, 40)
        technical60 = _clamp(components.get('technical60'), 0, 60)
        visible_score = round(_clamp(context40 + technical60), 1)

        # Execution strength is an ENTRY GATE only. Keep the analytical 40/60
        # score visible even while the gate is accumulating. Severe disclosures
        # still remain a hard zero/block.
        previous_score = float(out.get('score') or 0)
        previous_priority = float(out.get('priority_score') or previous_score)
        priority_bonus = max(0.0, previous_priority - previous_score)
        if not blocked:
            out['score'] = visible_score
            out['priority_score'] = round(visible_score + priority_bonus, 1)

        out['entry_gate_pass'] = bool(execution_ok and not blocked)
        out['execution_gate_pass'] = bool(execution_ok)
        out['execution_gate_reason'] = str(execution_reason or '')
        out['event_gate_pass'] = not blocked
        out['score_display_mode'] = '40/60_VISIBLE_EXECUTION_GATE_SEPARATE'

        reasons = list(out.get('reasons') or [])
        gate_text = f"진입 Gate · {execution_reason}" if execution_reason else '진입 Gate · 체결강도 확인'
        if gate_text not in reasons:
            reasons.insert(2 if len(reasons) >= 2 else len(reasons), gate_text)
        out['reasons'] = reasons
        return out

    m.candidate = candidate

    old_trade_scalp = m.trade_scalp

    def trade_scalp(market, candidates, now=None):
        rows = list(candidates or [])
        if str(market or '').upper() == 'KR':
            rows = [x for x in rows if bool(x.get('entry_gate_pass', True))]
        return old_trade_scalp(market, rows, now)

    m.trade_scalp = trade_scalp
