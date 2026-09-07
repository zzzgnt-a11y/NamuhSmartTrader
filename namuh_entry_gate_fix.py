from __future__ import annotations

import time
from datetime import datetime


def _blocked_event(q):
    blocked=bool(getattr(q,'event_blocked',False))
    try:
        blocked=blocked or any(bool(x.get('blocked')) for x in list(getattr(q,'events',[]) or []) if isinstance(x,dict))
    except Exception:
        pass
    return blocked


def apply(ns):
    core=ns.get('core') if isinstance(ns,dict) else None
    if core is None or getattr(core,'_NAMUH_ENTRY_GATE_FIX',False):
        return
    core._NAMUH_ENTRY_GATE_FIX=True

    try:
        import namuh_execution_exit_patch as rules
    except Exception as exc:
        print('NAMUH FINAL KR RULE import error:',exc,flush=True)
        return

    # ------------------------------------------------------------------
    # FINAL KR SCALP ENTRY OWNER
    # Signal conditions allowed here are ONLY:
    # - RECIPE80 + TECH20 total >= 72
    # - execution rule selected by the user
    # - severe negative disclosure/event block
    # Daily/volume/program/sector/news/technical are score components only.
    # Legacy 1m, orderbook, VI, 50/30/20, recipe_gate, daily/technical hard gates
    # and duplicate freshness gates are intentionally NOT consulted.
    # ------------------------------------------------------------------
    previous_trade_scalp=core.trade_scalp

    def trade_scalp(market,candidates,now=None):
        market=str(market or '').upper()
        if market!='KR':
            return previous_trade_scalp(market,candidates,now)

        now=(now or core.datetime.now(core.KST)).astimezone(core.KST)
        mins=now.hour*60+now.minute
        session=core.scalp_session(now)
        if session not in ('PRE08','REGULAR','LATE'):
            return
        # KRX closing-call window: no new entry. NXT hard stop at 19:59.
        if (15*60+19)<=mins<(15*60+40) or mins>=19*60+59:
            return

        rows=sorted(list(candidates or []),key=lambda x:float(x.get('score',0) or 0),reverse=True)
        for item in rows:
            if len(core.paper.market_positions('KR'))>=3:
                break
            code=str(item.get('code') or '').upper()
            if not code:
                continue
            if code in getattr(core,'protected',set()):
                continue
            if f'KR:{code}' in core.paper.positions:
                continue

            # Get the freshest available quote/execution value, but do not use
            # legacy freshness/1m/orderbook/VI gates.
            try:rules._refresh_kr_entry(core,code)
            except Exception:pass
            q=core.feed.quotes_for('KR').get(code)
            if q is None or float(getattr(q,'price',0) or 0)<=0:
                continue
            if _blocked_event(q):
                continue

            # Re-score execution immediately before entry so the total matches
            # the user's current 20/16/14/10/6/0 table.
            strength=float(getattr(q,'execution_strength',0) or 0)
            new_exec=float(rules._execution_points(strength))
            comps=dict(item.get('score_components') or {})
            old_exec=float(comps.get('execution20',0) or 0)
            total=round(max(0.0,min(100.0,float(item.get('score',0) or 0)-old_exec+new_exec)),1)
            exec_ok,exec_reason=rules.execution_gate(q,now.timestamp())

            item['score']=total
            item['priority_score']=total
            item['execution_strength']=strength
            item['execution_gate_pass']=bool(exec_ok)
            item['execution_gate_reason']=str(exec_reason)
            item['entry_gate_pass']=bool(exec_ok and total>=72.0)
            comps['execution20']=new_exec
            item['score_components']=comps

            if total<72.0 or not exec_ok:
                continue

            if core._buy_one('KR',item,'SCALP',session,now):
                print(
                    f"KR FINAL ENTRY BUY code={code} score={total:.1f} strength={strength:.1f} "
                    f"rule={exec_reason}",flush=True
                )
                break

    core.trade_scalp=trade_scalp

    # ------------------------------------------------------------------
    # FINAL KR SCALP EXIT OWNER
    # SCALP positions are NOT sold by legacy +3%, -1.5%, AI-score, VI or
    # pre-session rules. They are held until the user-selected session cutoff.
    # SMART and non-KR behaviour stays on the previous strategy path.
    # ------------------------------------------------------------------
    previous_mark_and_sell=core.mark_and_sell

    def mark_and_sell(market,scalp,smart,now=None):
        market=str(market or '').upper()
        if market!='KR':
            return previous_mark_and_sell(market,scalp,smart,now)

        now=(now or core.datetime.now(core.KST)).astimezone(core.KST)
        mins=now.hour*60+now.minute
        qs=core.feed.quotes_for('KR')
        fx=core._fx('KR')
        sold=False

        # Handle SCALP ourselves so no previous sell condition can touch them.
        scalp_keys=[]
        for p in list(core.paper.market_positions('KR')):
            q=qs.get(p.code)
            px=float(getattr(q,'price',0) or getattr(p,'current_price',0) or getattr(p,'avg_price',0) or 0)
            if px>0:
                try:core.paper.mark('KR',p.code,px,fx)
                except Exception:pass
            if str(getattr(p,'strategy','')).upper()!='SCALP':
                continue
            scalp_keys.append(p.key)

            entry_session=str(getattr(p,'entry_session','') or '').upper()
            try:
                entered=datetime.fromtimestamp(float(getattr(p,'entry_ts',0) or 0),core.KST)
                entry_mins=entered.hour*60+entered.minute
            except Exception:
                entry_mins=0

            # PRE08/LATE are NXT sessions. Regular KRX entries exit at 15:19.
            is_nxt=entry_session in ('PRE08','LATE','NXT','AFTER') or entry_mins>=15*60+40
            deadline=19*60+59 if is_nxt else 15*60+19
            if mins<deadline or px<=0:
                continue

            reason='NXT 19:59 장마감 강제청산' if is_nxt else 'KRX 15:19 동시호가 전 강제청산'
            if core.paper.sell('KR',p.code,px,fx,reason):
                sold=True
                print(f'KR FINAL FORCE EXIT code={p.code} reason={reason} price={px}',flush=True)

        if sold:
            try:core._persist_paper()
            except Exception:pass

        # Preserve SMART exit management without exposing SCALP positions to the
        # old KR sell chain: temporarily hide only SCALP positions during call.
        hidden={}
        try:
            for k in scalp_keys:
                if k in core.paper.positions:
                    hidden[k]=core.paper.positions.pop(k)
            previous_mark_and_sell('KR',scalp,smart,now)
        finally:
            for k,p in hidden.items():
                if k not in core.paper.positions:
                    core.paper.positions[k]=p

    core.mark_and_sell=mark_and_sell

    # Compatibility status endpoint: KR entry status reflects only the current
    # execution rule and an actual price. It is no longer an independent gate.
    old_status=getattr(core.feed,'entry_data_status',None)
    if callable(old_status):
        def entry_data_status(market,code,now_ts=None):
            market=str(market or '').upper()
            if market!='KR':
                return old_status(market,code,now_ts)
            q=core.feed.quotes_for('KR').get(str(code).upper())
            if q is None or float(getattr(q,'price',0) or 0)<=0:
                return False,'현재가 미수신'
            ok,reason=rules.execution_gate(q,float(now_ts or time.time()))
            return bool(ok),str(reason)
        core.feed.entry_data_status=entry_data_status

    try:
        old_health=core.health_payload
        def health():
            d=dict(old_health())
            d['kr_scalp_final_gate_owner']='USER_RULES_ONLY'
            d['kr_scalp_entry_rules']=[
                'RECIPE80+TECH20 total>=72',
                'execution 110/105/100 immediate; 95 30s rise; 90 60s rise; <90 block',
                'severe negative event block',
            ]
            d['removed_legacy_entry_gates']=['1m','orderbook','VI','50/30/20','recipe_gate','daily_hard_gate','technical_hard_gate','legacy_freshness_gate']
            d['kr_scalp_exit_rules']=['KRX 15:19','NXT 19:59']
            d['removed_legacy_scalp_exits']=['+3%','-1.5%','AI score<46','VI exit','08:49 pre-force-exit']
            return d
        core.health_payload=health
    except Exception:
        pass

    print('NAMUH FINAL KR USER RULES active: old scalp entry/sell gates removed; KRX 15:19 / NXT 19:59',flush=True)
