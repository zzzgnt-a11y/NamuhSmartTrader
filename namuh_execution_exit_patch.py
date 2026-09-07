from __future__ import annotations

import time
from datetime import datetime


def _execution_points(strength):
    s=float(strength or 0)
    if s>=110:return 20.0
    if s>=105:return 17.0
    if s>=100:return 14.0
    if s>=95:return 11.0
    if s>=90:return 8.0
    return max(0.0,(s-70.0)/20.0*8.0)


def _checkpoint_values(q, now_ts=None):
    now_ts=float(now_ts or time.time())
    hist=[]
    for row in list(getattr(q,'execution_history',[]) or []):
        try:
            ts=float(row[0]);val=float(row[1])
        except Exception:
            continue
        if ts<=now_ts and now_ts-ts<=120:
            hist.append((ts,val))
    hist.sort(key=lambda x:x[0])
    current=float(getattr(q,'execution_strength',0) or 0)
    if not hist:
        return None
    if now_ts-hist[0][0] < 30.0:
        return None
    vals=[]
    for age in (30,20,10):
        target=now_ts-age
        cand=[v for ts,v in hist if ts<=target]
        if not cand:
            return None
        vals.append(float(cand[-1]))
    vals.append(current)
    return vals


def execution_gate_30s(q, now_ts=None):
    s=float(getattr(q,'execution_strength',0) or 0)
    if s>=110:
        return True,'체결강도 110+ 즉시 통과'
    if s<90:
        return False,'체결강도 90 미만'
    vals=_checkpoint_values(q,now_ts)
    if vals is None:
        return False,'체결강도 30초 추세 축적 중'
    if s>=100:
        if min(vals)<100:
            return False,'체결강도 100+ 30초 유지 대기'
        if all(vals[i+1] >= vals[i] for i in range(len(vals)-1)):
            return True,'체결강도 100+ · 30초 무하락'
        return False,'체결강도 100+이나 30초 내 하락 발생'
    if min(vals)<90:
        return False,'체결강도 90+ 30초 유지 대기'
    if all(vals[i+1] > vals[i] for i in range(len(vals)-1)):
        return True,'체결강도 90+ · 30초 연속 상승'
    return False,'체결강도 90+이나 30초 연속 상승 미충족'


def apply(ns):
    core=ns.get('core') if isinstance(ns,dict) else None
    if core is None or getattr(core,'_NAMUH_EXEC_EXIT_PATCHED',False):
        return
    core._NAMUH_EXEC_EXIT_PATCHED=True

    # Replace only the KR RECIPE80 execution gate; coin/other strategies stay untouched.
    try:
        import namuh_recipe8020_patch as recipe
        def execution20(q,market):
            s=float(getattr(q,'execution_strength',0) or 0)
            if str(market or '').upper()!='KR':
                return 0.0,True,'미장 체결강도 점수 미사용'
            pts=_execution_points(s)
            ok,reason=execution_gate_30s(q)
            return round(max(0.0,min(20.0,pts)),1),bool(ok),str(reason)
        recipe._execution20=execution20
    except Exception as exc:
        print('NAMUH EXEC GATE PATCH ERROR:',exc,flush=True)

    # Force-flat KR positions before KRX closing call auction, and at NXT close.
    old_sell=core.mark_and_sell
    def mark_and_sell(market,scalp,smart,now=None):
        now=(now or core.datetime.now(core.KST)).astimezone(core.KST)
        if str(market).upper()=='KR':
            mins=now.hour*60+now.minute
            fx=core._fx('KR')
            qs=core.feed.quotes_for('KR')
            sold=False
            for p in list(core.paper.market_positions('KR')):
                try:
                    entered=datetime.fromtimestamp(float(getattr(p,'entry_ts',0) or 0),core.KST)
                    entry_mins=entered.hour*60+entered.minute
                except Exception:
                    entry_mins=0
                # Positions opened in the NXT after-market (15:40+) may run to 19:59.
                nxt_after=entry_mins>=15*60+40
                deadline=19*60+59 if nxt_after else 15*60+19
                if mins < deadline:
                    continue
                q=qs.get(p.code)
                px=float(getattr(q,'price',0) or getattr(p,'current_price',0) or getattr(p,'avg_price',0) or 0)
                if px<=0:
                    continue
                try:core.paper.mark('KR',p.code,px,fx)
                except Exception:pass
                reason='NXT 19:59 장마감 강제청산' if nxt_after else 'KRX 15:19 동시호가 전 강제청산'
                if core.paper.sell('KR',p.code,px,fx,reason):
                    sold=True
                    print(f'FORCE EXIT {p.code} {reason} price={px}',flush=True)
            if sold:
                try:core._persist_paper()
                except Exception:pass
        return old_sell(market,scalp,smart,now)
    core.mark_and_sell=mark_and_sell

    # Do not re-enter after the forced exit deadline / during the KRX-NXT handoff.
    old_trade=core.trade_scalp
    def trade_scalp(market,candidates,now=None):
        now=(now or core.datetime.now(core.KST)).astimezone(core.KST)
        if str(market).upper()=='KR':
            mins=now.hour*60+now.minute
            if (15*60+19)<=mins<(15*60+40):
                return
            if mins>=19*60+59:
                return
        return old_trade(market,candidates,now)
    core.trade_scalp=trade_scalp

    try:
        old_health=core.health_payload
        def health():
            d=dict(old_health())
            d['execution_gate_model']='110 immediate / 100+ 30s non-falling / 90+ 30s rising'
            d['krx_force_exit']='15:19'
            d['nxt_force_exit']='19:59'
            return d
        core.health_payload=health
    except Exception:
        pass

    print('NAMUH EXEC/EXIT PATCH active: 110 immediate; 100+ flat/rise 30s; 90+ rise 30s; KRX 15:19; NXT 19:59',flush=True)
