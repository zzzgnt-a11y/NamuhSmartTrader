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
    old = core.candidate
    if getattr(old, '_namuh_threshold70_absolute', False):
        _INSTALLED = True
        return True

    def candidate(*args, **kwargs):
        out = old(*args, **kwargs)
        if not isinstance(out, dict):
            return out
        try:
            market = str(args[1] if len(args) > 1 else kwargs.get('market', '')).upper()
            smart = bool(args[2] if len(args) > 2 else kwargs.get('smart', False))
            if smart or market not in ('KR', 'US'):
                return out
            c1 = dict(out.get('condition1') or {})
            if not c1:
                return out
            gates = dict(c1.get('gates') or {})
            total = _f(c1.get('score'), _f(out.get('score')))
            blocked = bool(gates.get('event_block', False))
            hard = bool(gates.get('daily') and gates.get('minute1m') and gates.get('execution') and gates.get('orderbook'))
            gate = bool(not blocked and hard and total >= 70.0)
            gates.pop('total75', None)
            gates['total70'] = total >= 70.0
            gates['total_threshold'] = total >= 70.0
            c1['entry_threshold'] = 70.0
            c1['gate'] = gate
            c1['gates'] = gates
            c1['threshold_owner'] = 'condition1 final 70'
            out['condition1'] = c1
            out['condition1_gate_pass'] = gate
            labels = [x for x in list(out.get('condition_labels') or []) if str(x) != '조건1']
            if gate:
                labels.insert(0, '조건1')
            out['condition_labels'] = list(dict.fromkeys(labels))
            out['condition_display'] = '복합조건' if len([x for x in out['condition_labels'] if str(x).startswith('조건')]) > 1 else (out['condition_labels'][0] if out['condition_labels'] else '')
        except Exception as exc:
            out['threshold70_absolute_error'] = str(exc)[:180]
        return out

    candidate._namuh_threshold70_absolute = True
    core.candidate = candidate
    _INSTALLED = True
    print('NAMUH CONDITION1 FINAL THRESHOLD active: KR/US C1>=70', flush=True)
    return True
