from __future__ import annotations

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
    now_ts=float(now_ts or time.time());hist=[]
    for row in list(getattr(q,'execution_history',[]) or []):
        try:ts=float(row[0]);val=float(row[1])
        except Exception:continue
        if ts<=now_ts and now_ts-ts<=max_age:hist.append((ts,val))
    hist.sort(key=lambda x:x[0]);return now_ts,hist


def _sample_values(q, ages, now_ts=None):
    now_ts,hist=_history(q,now_ts,max_age=max(120,max(ages or [0])+10))
    if not hist:return None
    current=float(getattr(q,'execution_strength',0) or 0)
    if now_ts-hist[0][0] < float(max(ages or [0])):return None
    vals=[]
    for age in ages:
        if age==0:vals.append(current);continue
        target=now_ts-float(age);cand=[v for ts,v in hist if ts<=target]
        if not cand:return None
        vals.append(float(cand[-1]))
    return vals


def _checkpoint_values_30s_5s(q, now_ts=None):return _sample_values(q,tuple(range(30,-1,-5)),now_ts)
def _checkpoint_values_60s_5s(q, now_ts=None):return _sample_values(q,tuple(range(60,-1,-5)),now_ts)


def _net_rise_reason(vals, floor, label):
    if vals is None:return False,f'체결강도 {label} 추세 축적 중(5초 간격)'
    start=float(vals[0]);end=float(vals[-1])
    rises=sum(1 for a,b in zip(vals,vals[1:]) if b>a);falls=sum(1 for a,b in zip(vals,vals[1:]) if b<a)
    flats=max(0,len(vals)-1-rises-falls)
    if start<floor:return False,f'체결강도 {label} 시작값 {start:.1f} < {floor:.0f} 대기'
    if end>start:return True,f'체결강도 {label} 순상승 {start:.1f}→{end:.1f} · 상승{rises}/하락{falls}/보합{flats}'
    return False,f'체결강도 {label} 순상승 미충족 {start:.1f}→{end:.1f} · 중간하락 허용'


def execution_gate(q, now_ts=None):
    s=float(getattr(q,'execution_strength',0) or 0)
    if s>=110:return True,'체결강도 110+ · 20/20 즉시 통과'
    if s>=105:return True,'체결강도 105+ · 16/20 즉시 통과'
    if s>=100:return True,'체결강도 100+ · 14/20 즉시 통과'
    if s>=95:return _net_rise_reason(_checkpoint_values_30s_5s(q,now_ts),95.0,'95+ · 30초')
    if s>=90:return _net_rise_reason(_checkpoint_values_60s_5s(q,now_ts),90.0,'90~94.9 · 1분')
    return False,'체결강도 90 미만 · 0/20 · 미진입'


def _daily20_from_open(core,q,recipe):
    b=recipe._completed_prev_bar(core,q)
    if not b:return 0.0,None
    prev_open=float(b.get('open') or 0);prev_close=float(b.get('close') or 0)
    prev_high=float(b.get('high') or 0);prev_low=float(b.get('low') or 0)
    today_open=float(getattr(q,'open',0) or 0)
    if prev_high<=0 or prev_low<=0 or today_open<=0:return 0.0,None
    mid=(prev_high+prev_low)/2.0;pts=0.0
    if today_open>=mid:
        pts=12.0;dist=(today_open/mid-1.0)*100.0;pts+=min(4.0,max(0.0,dist/2.0*4.0))
    else:
        gap=(mid-today_open)/mid*100.0;pts=max(0.0,4.0-gap/2.0*4.0)
    if prev_close>0 and today_open>=prev_close:pts+=2.0
    if today_open>=prev_high:pts+=2.0
    pts=round(max(0.0,min(20.0,pts)),1)
    return pts,{'prev_open':prev_open,'prev_close':prev_close,'prev_high':prev_high,'prev_low':prev_low,
                'mid':mid,'today_open':today_open,'price':today_open,'basis':'today_open_vs_prev_high_low_mid'}


def _refresh_kr_entry(core,code):
    """Refresh an eligible candidate and prefer a response that also refreshes execution strength."""
    try:
        from nhplug import call
        best_price=False
        for market_cd in core.feed._market_order():
            try:
                data=call('/krstock/quote/v1/currentPrice',{'iem_cd':str(code),'market_cd':market_cd})
                core.feed._apply_kr(str(code),data)
                q=core.feed.quotes_for('KR').get(str(code))
                if q is None:continue
                best_price=best_price or float(getattr(q,'price',0) or 0)>0
                eh=list(getattr(q,'execution_history',[]) or [])
                if best_price and eh and time.time()-float(eh[-1][0])<=5:return True
            except Exception:continue
        return best_price
    except Exception:return False


def apply(ns):
    core=ns.get('core') if isinstance(ns,dict) else None
    if core is None or getattr(core,'_NAMUH_EXEC_EXIT_PATCHED',False):return
    core._NAMUH_EXEC_EXIT_PATCHED=True

    try:
        import namuh_recipe8020_patch as recipe
        def execution20(q,market):
            s=float(getattr(q,'execution_strength',0) or 0)
            if str(market or '').upper()!='KR':return 0.0,True,'미장 체결강도 점수 미사용'
            pts=_execution_points(s);ok,reason=execution_gate(q)
            return round(max(0.0,min(20.0,pts)),1),bool(ok),str(reason)
        recipe._execution20=execution20
        recipe._daily20=lambda core_arg,q:_daily20_from_open(core_arg,q,recipe)
    except Exception as exc:print('NAMUH DAILY/EXEC PATCH ERROR:',exc,flush=True)

    # Candidate-level final freshness: old investor-flow freshness is not a hard
    # gate in RECIPE80+TECH20. Price and execution still must be current.
    old_entry_status=getattr(core.feed,'entry_data_status',None);entry_refresh_at={}
    if callable(old_entry_status):
        def entry_data_status(market,code,now_ts=None):
            market=str(market or '').upper();now_ts=float(now_ts or time.time())
            if market!='KR':return old_entry_status(market,code,now_ts)
            code=str(code).upper();q=core.feed.quotes_for('KR').get(code)
            eh=list(getattr(q,'execution_history',[]) or []) if q else []
            price_stale=(not q or float(getattr(q,'price',0) or 0)<=0 or now_ts-float(getattr(q,'updated_at',0) or 0)>20)
            exec_stale=(not eh or now_ts-float(eh[-1][0])>20)
            if (price_stale or exec_stale) and now_ts-float(entry_refresh_at.get(code,0) or 0)>=5:
                entry_refresh_at[code]=now_ts;_refresh_kr_entry(core,code)
                q=core.feed.quotes_for('KR').get(code);eh=list(getattr(q,'execution_history',[]) or []) if q else []
            if not q or float(getattr(q,'price',0) or 0)<=0:return False,'현재가 미수신'
            if now_ts-float(getattr(q,'updated_at',0) or 0)>25:return False,'현재가 즉시 재조회 실패/25초 초과'
            if not eh or now_ts-float(eh[-1][0])>30:return False,'체결강도 즉시 재조회 실패/30초 초과'
            ok,reason=execution_gate(q,now_ts)
            if not ok:return False,'최신 '+reason
            return True,'정상(후보 현재가·체결강도 즉시 재조회)'
        core.feed.entry_data_status=entry_data_status

    old_sell=core.mark_and_sell
    def mark_and_sell(market,scalp,smart,now=None):
        now=(now or core.datetime.now(core.KST)).astimezone(core.KST)
        if str(market).upper()=='KR':
            mins=now.hour*60+now.minute;fx=core._fx('KR');qs=core.feed.quotes_for('KR');sold=False
            for p in list(core.paper.market_positions('KR')):
                try:
                    entered=datetime.fromtimestamp(float(getattr(p,'entry_ts',0) or 0),core.KST);entry_mins=entered.hour*60+entered.minute
                except Exception:entry_mins=0
                nxt_after=entry_mins>=15*60+40;deadline=19*60+59 if nxt_after else 15*60+19
                if mins<deadline:continue
                q=qs.get(p.code);px=float(getattr(q,'price',0) or getattr(p,'current_price',0) or getattr(p,'avg_price',0) or 0)
                if px<=0:continue
                try:core.paper.mark('KR',p.code,px,fx)
                except Exception:pass
                reason='NXT 19:59 장마감 강제청산' if nxt_after else 'KRX 15:19 동시호가 전 강제청산'
                if core.paper.sell('KR',p.code,px,fx,reason):sold=True;print(f'FORCE EXIT {p.code} {reason} price={px}',flush=True)
            if sold:
                try:core._persist_paper()
                except Exception:pass
        return old_sell(market,scalp,smart,now)
    core.mark_and_sell=mark_and_sell

    # namuh_recipe8020_patch already owns the final scalp wrapper and calls the
    # pre-v34 base function, so legacy runtime_v34 1m confirmation is bypassed.
    old_trade=core.trade_scalp;diag_at=[0.0]
    def trade_scalp(market,candidates,now=None):
        now=(now or core.datetime.now(core.KST)).astimezone(core.KST)
        if str(market).upper()=='KR':
            mins=now.hour*60+now.minute
            if (15*60+19)<=mins<(15*60+40) or mins>=19*60+59:return
            # Refresh and re-score the execution component before the actual buy.
            for x in list(candidates or []):
                if float(x.get('score',0) or 0)<72 or not bool(x.get('entry_gate_pass',False)):continue
                code=str(x.get('code') or '')
                _refresh_kr_entry(core,code)
                q=core.feed.quotes_for('KR').get(code)
                if not q:continue
                strength=float(getattr(q,'execution_strength',0) or 0);new_exec=_execution_points(strength)
                old_exec=float((x.get('score_components') or {}).get('execution20',0) or 0)
                new_total=round(max(0.0,min(100.0,float(x.get('score',0) or 0)-old_exec+new_exec)),1)
                gate_ok,gate_reason=execution_gate(q,now.timestamp())
                x['score']=new_total;x['priority_score']=new_total;x['execution_gate_pass']=bool(gate_ok)
                x['execution_gate_reason']=gate_reason;x['entry_gate_pass']=bool(gate_ok and new_total>=72)
                if isinstance(x.get('score_components'),dict):x['score_components']['execution20']=new_exec
            eligible=[x for x in list(candidates or []) if float(x.get('score',0) or 0)>=72 and bool(x.get('entry_gate_pass',False))]
            before={getattr(p,'code','') for p in core.paper.market_positions('KR')}
            out=old_trade(market,candidates,now)
            after={getattr(p,'code','') for p in core.paper.market_positions('KR')};added=sorted(after-before)
            if added:print(f'KR ENTRY BUY codes={added}',flush=True)
            elif eligible and time.time()-diag_at[0]>=15:
                diag_at[0]=time.time();rows=[]
                for x in eligible[:5]:
                    code=str(x.get('code') or '')
                    try:ok,reason=core.feed.entry_data_status('KR',code,now.timestamp())
                    except Exception as exc:ok,reason=False,str(exc)
                    rows.append(f"{code}:{float(x.get('score',0) or 0):.1f}:{'OK' if ok else 'BLOCK'}:{reason}")
                print('KR ENTRY DIAG '+' | '.join(rows),flush=True)
            return out
        return old_trade(market,candidates,now)
    core.trade_scalp=trade_scalp

    try:
        old_health=core.health_payload
        def health():
            d=dict(old_health())
            d['daily20_model']='today open vs previous (high+low)/2'
            d['execution_gate_model']='110=20 immediate / 105=16 immediate / 100=14 immediate / 95=10 + 30s net-rise / 90=6 + 60s net-rise / <90 blocked'
            d['entry_freshness_model']='eligible KR refresh+rescore; price<=25s; execution<=30s; investor-flow not hard gate'
            d['runtime_v34_1m_scalp_gate_bypassed']=True
            d['krx_force_exit']='15:19';d['nxt_force_exit']='19:59'
            return d
        core.health_payload=health
    except Exception:pass

    print('NAMUH DAILY/EXEC PATCH active: daily=today open vs prev (high+low)/2; EXEC 20/16/14/10/6/0; eligible refresh+rescore ON; 1m scalp gate OFF; KRX 15:19; NXT 19:59',flush=True)
