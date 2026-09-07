from __future__ import annotations

import sys
import threading
import time
from datetime import datetime


def _execution_points(strength):
    s=float(strength or 0)
    if s>=110:return 20.0
    if s>=105:return 16.0
    if s>=100:return 14.0
    if s>=95:return 10.0
    if s>=90:return 6.0
    return 0.0


def _history(q, now_ts=None, max_age=120):
    now_ts=float(now_ts or time.time())
    hist=[]
    for row in list(getattr(q,'execution_history',[]) or []):
        try:
            ts=float(row[0]);val=float(row[1])
        except Exception:
            continue
        if ts<=now_ts and now_ts-ts<=max_age:
            hist.append((ts,val))
    hist.sort(key=lambda x:x[0])
    return now_ts,hist


def _sample_values(q, ages, now_ts=None):
    now_ts,hist=_history(q,now_ts,max_age=max(120,max(ages or [0])+10))
    if not hist:
        return None
    current=float(getattr(q,'execution_strength',0) or 0)
    if now_ts-hist[0][0] < float(max(ages or [0])):
        return None
    vals=[]
    for age in ages:
        if age==0:
            vals.append(current)
            continue
        target=now_ts-float(age)
        cand=[v for ts,v in hist if ts<=target]
        if not cand:
            return None
        vals.append(float(cand[-1]))
    return vals


def _checkpoint_values_30s_5s(q, now_ts=None):
    return _sample_values(q,tuple(range(30,-1,-5)),now_ts)


def _checkpoint_values_60s_5s(q, now_ts=None):
    return _sample_values(q,tuple(range(60,-1,-5)),now_ts)


def _net_rise_reason(vals, floor, label):
    if vals is None:
        return False,f'체결강도 {label} 추세 축적 중(5초 간격)'
    start=float(vals[0]);end=float(vals[-1])
    rises=sum(1 for a,b in zip(vals,vals[1:]) if b>a)
    falls=sum(1 for a,b in zip(vals,vals[1:]) if b<a)
    flats=max(0,len(vals)-1-rises-falls)
    if start<floor:
        return False,f'체결강도 {label} 시작값 {start:.1f} < {floor:.0f} 대기'
    if end>start:
        return True,f'체결강도 {label} 순상승 {start:.1f}→{end:.1f} · 상승{rises}/하락{falls}/보합{flats}'
    return False,f'체결강도 {label} 순상승 미충족 {start:.1f}→{end:.1f} · 중간하락 허용'


def execution_gate(q, now_ts=None):
    s=float(getattr(q,'execution_strength',0) or 0)
    if s>=110:
        return True,'체결강도 110+ · 20/20 즉시 통과'
    if s>=105:
        return True,'체결강도 105+ · 16/20 즉시 통과'
    if s>=100:
        return True,'체결강도 100+ · 14/20 즉시 통과'
    if s>=95:
        vals=_checkpoint_values_30s_5s(q,now_ts)
        return _net_rise_reason(vals,95.0,'95+ · 30초')
    if s>=90:
        vals=_checkpoint_values_60s_5s(q,now_ts)
        return _net_rise_reason(vals,90.0,'90~94.9 · 1분')
    return False,'체결강도 90 미만 · 0/20 · 미진입'


def _daily20_from_open(core,q,recipe):
    b=recipe._completed_prev_bar(core,q)
    if not b:return 0.0,None
    prev_open=float(b.get('open') or 0)
    prev_close=float(b.get('close') or 0)
    prev_high=float(b.get('high') or 0)
    prev_low=float(b.get('low') or 0)
    today_open=float(getattr(q,'open',0) or 0)
    if prev_high<=0 or prev_low<=0 or today_open<=0:return 0.0,None
    mid=(prev_high+prev_low)/2.0
    pts=0.0
    if today_open>=mid:
        pts=12.0
        dist=(today_open/mid-1.0)*100.0
        pts+=min(4.0,max(0.0,dist/2.0*4.0))
    else:
        gap=(mid-today_open)/mid*100.0
        pts=max(0.0,4.0-gap/2.0*4.0)
    if prev_close>0 and today_open>=prev_close:pts+=2.0
    if today_open>=prev_high:pts+=2.0
    pts=round(max(0.0,min(20.0,pts)),1)
    return pts,{
        'prev_open':prev_open,'prev_close':prev_close,'prev_high':prev_high,'prev_low':prev_low,
        'mid':mid,'today_open':today_open,'price':today_open,
        'basis':'today_open_vs_prev_high_low_mid'
    }


def _install_late_scalp_bypass(core):
    core._NAMUH_SCALP_1M_BYPASSED=False

    def worker():
        # runtime_server_v34 installs its legacy five-1m-bar wrapper after app import.
        # Wait for that outer wrapper, then replace only the SCALP layer with the
        # pre-v34 trade function so the user-selected RECIPE80+TECH20 gate is final.
        for _ in range(300):
            try:
                current=getattr(core,'trade_scalp',None)
                owner=None
                prev=None
                for mod in list(sys.modules.values()):
                    if mod is None:continue
                    cand=getattr(mod,'_prev_trade_scalp',None)
                    cur_v34=getattr(mod,'trade_scalp_v34',None)
                    if callable(cand) and callable(cur_v34) and current is cur_v34:
                        owner=mod;prev=cand;break
                if callable(prev):
                    def trade_scalp_no_1m(market,candidates,now=None):
                        rows=[x for x in list(candidates or [])
                              if float(x.get('score',0) or 0)>=72.0
                              and bool(x.get('entry_gate_pass',False))]
                        return prev(market,rows,now)
                    core.trade_scalp=trade_scalp_no_1m
                    core._NAMUH_SCALP_1M_BYPASSED=True
                    print('NAMUH SCALP FINAL GATE: legacy runtime_v34 1m trend filter BYPASSED',flush=True)
                    return
            except Exception as exc:
                print('NAMUH SCALP BYPASS retry:',exc,flush=True)
            time.sleep(0.1)
        print('NAMUH SCALP BYPASS WARNING: runtime_v34 wrapper not found',flush=True)

    threading.Thread(target=worker,name='namuh-scalp-final-gate',daemon=True).start()


def apply(ns):
    core=ns.get('core') if isinstance(ns,dict) else None
    if core is None or getattr(core,'_NAMUH_EXEC_EXIT_PATCHED',False):
        return
    core._NAMUH_EXEC_EXIT_PATCHED=True

    # Replace only KR RECIPE80 daily/execution rules; coin/US logic stays untouched.
    try:
        import namuh_recipe8020_patch as recipe
        def execution20(q,market):
            s=float(getattr(q,'execution_strength',0) or 0)
            if str(market or '').upper()!='KR':
                return 0.0,True,'미장 체결강도 점수 미사용'
            pts=_execution_points(s)
            ok,reason=execution_gate(q)
            return round(max(0.0,min(20.0,pts)),1),bool(ok),str(reason)
        def daily20(core_arg,q):
            return _daily20_from_open(core_arg,q,recipe)
        recipe._execution20=execution20
        recipe._daily20=daily20
    except Exception as exc:
        print('NAMUH DAILY/EXEC PATCH ERROR:',exc,flush=True)

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

    _install_late_scalp_bypass(core)

    try:
        old_health=core.health_payload
        def health():
            d=dict(old_health())
            d['daily20_model']='today open vs previous (high+low)/2'
            d['execution_gate_model']='110=20 immediate / 105=16 immediate / 100=14 immediate / 95=10 + 30s net-rise / 90=6 + 60s net-rise / <90 blocked'
            d['runtime_v34_1m_scalp_gate_bypassed']=bool(getattr(core,'_NAMUH_SCALP_1M_BYPASSED',False))
            d['krx_force_exit']='15:19'
            d['nxt_force_exit']='19:59'
            return d
        core.health_payload=health
    except Exception:
        pass

    print('NAMUH DAILY/EXEC PATCH active: daily=today open vs prev (high+low)/2; EXEC 20/16/14/10/6/0; KRX 15:19; NXT 19:59',flush=True)
