from __future__ import annotations

import time


def apply(ns):
    core=ns.get('core') if isinstance(ns,dict) else None
    if core is None or getattr(core,'_NAMUH_ENTRY_GATE_FIX',False):
        return
    core._NAMUH_ENTRY_GATE_FIX=True

    try:
        import namuh_execution_exit_patch as rules
    except Exception as exc:
        print('NAMUH ENTRY GATE FIX import error:',exc,flush=True)
        return

    old_status=getattr(core.feed,'entry_data_status',None)
    if not callable(old_status):
        return

    refresh_at={}
    def entry_data_status(market,code,now_ts=None):
        market=str(market or '').upper()
        now_ts=float(now_ts or time.time())
        if market!='KR':
            return old_status(market,code,now_ts)

        code=str(code).upper()
        q=core.feed.quotes_for('KR').get(code)
        price_stale=(
            not q
            or float(getattr(q,'price',0) or 0)<=0
            or now_ts-float(getattr(q,'updated_at',0) or 0)>20
        )
        if price_stale and now_ts-float(refresh_at.get(code,0) or 0)>=5:
            refresh_at[code]=now_ts
            try:rules._refresh_kr_entry(core,code)
            except Exception:pass
            q=core.feed.quotes_for('KR').get(code)

        if not q or float(getattr(q,'price',0) or 0)<=0:
            return False,'현재가 미수신'
        if now_ts-float(getattr(q,'updated_at',0) or 0)>25:
            return False,'현재가 25초 초과'

        # Do not apply a second execution-history freshness gate here.
        # 110/105/100 are immediate by the user's rule. 95/90 timing/history
        # requirements are already enforced inside execution_gate itself.
        ok,reason=rules.execution_gate(q,now_ts)
        if not ok:
            return False,str(reason)
        return True,'정상(중복 체결강도 지연 Gate 제거)'

    core.feed.entry_data_status=entry_data_status
    print('NAMUH ENTRY GATE FIX active: duplicate execution-history freshness blocker OFF',flush=True)
