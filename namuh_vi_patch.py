from __future__ import annotations

import math
import threading


def _tick(p):
    p=float(p or 0)
    if p<2000:return 1
    if p<5000:return 5
    if p<20000:return 10
    if p<50000:return 50
    if p<200000:return 100
    if p<500000:return 500
    return 1000


def _floor_tick(p):
    p=float(p or 0)
    if p<=0:return None
    t=_tick(p);return int(math.floor((p+1e-9)/t)*t)


def _one_below(p):
    p=float(p or 0)
    if p<=0:return None
    probe=max(0,p-1e-7);t=_tick(probe);v=math.floor(probe/t)*t
    if v>=p:v-=t
    return max(0,int(round(v)))


def apply(m):
    if getattr(m,'_NAMUH_VI_PATCHED',False):return
    m._NAMUH_VI_PATCHED=True
    m._NAMUH_VI_LOCK=threading.RLock();key='vi_reentry_v2'
    try:r=m.store.load_json(key,{}) or {};state=r if isinstance(r,dict) else {}
    except Exception:state={}
    m._NAMUH_VI_STATE=state
    def persist():
        try:m.store.save_json(key,state)
        except Exception:pass
    # First static-VI reference used by the current strategy: session/open reference +10%.
    # We deliberately do not pretend to know a later exchange-reset VI reference without an actual VI event feed.
    m._namuh_vi_trigger=lambda open_price:_floor_tick(float(open_price or 0)*1.10)
    m._namuh_vi_target=_one_below

    old_sell=m.mark_and_sell
    def mark_and_sell(market,scalp,smart,now=None):
        now=(now or m.datetime.now(m.KST)).astimezone(m.KST);fx=m._fx(market)
        if market=='US' and fx<=0:return
        qs=m.feed.quotes_for(market);sm={x['code']:x['score'] for x in scalp};mm={x['code']:x['score'] for x in smart};items={x['code']:x for x in scalp};items.update({x['code']:x for x in smart})
        for p in list(m.paper.market_positions(market)):
            q=qs.get(p.code)
            if not q or q.price<=0:continue
            m.paper.mark(market,p.code,q.price,fx);score=(mm if p.strategy=='SMART' else sm).get(p.code,50);reason='';sell=float(q.price);it=items.get(p.code) or {};target=it.get('vi_target') or it.get('vi_pre');trigger=it.get('vi_trigger')
            vi_mode=bool(it.get('vi_mode'))
            vi=bool(market=='KR' and p.strategy!='SMART' and vi_mode and target and trigger and float(target)>float(p.avg_price) and float(q.price)>=float(target))
            if market=='KR' and m.must_force_sell_pre(p,now):reason='08:49 프리세션 강제청산'
            elif vi:reason='VI 발동가 미도달 · 직전 1호가 익절';sell=float(target)
            elif p.pnl_pct>=3 and not (market=='KR' and p.strategy!='SMART' and vi_mode and target and float(target)>float(p.avg_price)):reason='목표수익 +3% 도달'
            elif p.pnl_pct<=-1.5:reason='손절 기준 도달'
            elif score<46:reason='AI 점수 이탈'
            if reason and m.paper.sell(market,p.code,sell,fx,reason):
                if vi:
                    with m._NAMUH_VI_LOCK:state[p.code]={'created_at':now.timestamp(),'vi_trigger':float(trigger),'vi_target':float(target),'exit_price':sell,'vi_triggered':False,'triggered_at':0,'low':None}
                    persist()
                try:m._persist_paper()
                except Exception:pass
    m.mark_and_sell=mark_and_sell

    def update(code,q,ts):
        changed=False
        with m._NAMUH_VI_LOCK:
            st=state.get(code)
            if not isinstance(st,dict):return None
            if ts-float(st.get('created_at') or ts)>21600:state.pop(code,None);changed=True;st=None
            if st:
                px=float(q.price or 0);tr=float(st.get('vi_trigger') or 0)
                if not st.get('vi_triggered') and tr>0 and px>=tr:st['vi_triggered']=True;st['triggered_at']=ts;st['low']=px;changed=True
                if st.get('vi_triggered') and px>0 and (st.get('low') is None or px<float(st['low'])):st['low']=px;changed=True
        if changed:persist()
        return dict(st) if isinstance(st,dict) else None
    def ready(item,q,ts):
        code=str(item.get('code') or '').upper();st=update(code,q,ts)
        if not st:return True
        if not st.get('vi_triggered'):return False
        if ts-float(st.get('triggered_at') or ts)<120:return False
        tr=float(st.get('vi_trigger') or 0);low=float(st.get('low') or 0);px=float(q.price or 0)
        if tr<=0 or low<=0 or px<=0:return False
        if low>tr*.995:return False
        if px<low*1.003:return False
        if not item.get('recipe_gate',True):return False
        ep=item.get('execution_points')
        if ep is not None and float(ep)<8:return False
        return True

    old_trade=m.trade_scalp
    def trade_scalp(market,candidates,now=None):
        now=(now or m.datetime.now(m.KST)).astimezone(m.KST);session=m.scalp_session(now) if market=='KR' else 'US'
        if market=='KR' and session not in ('PRE08','REGULAR','LATE'):return
        for it in candidates:
            if len(m.paper.market_positions(market))>=3 or float(it.get('score',0) or 0)<72:break
            code=it['code']
            if market=='KR' and code in m.protected:continue
            if f'{market}:{code}' in m.paper.positions or not it.get('recipe_gate',True):continue
            q=m.feed.quotes_for(market).get(code)
            if not q or q.price<=0:continue
            if market=='KR':
                target=it.get('vi_target') or it.get('vi_pre')
                if target and float(q.price)>=float(target):continue
                if not ready(it,q,now.timestamp()):continue
            fresh,_=m.feed.entry_data_status(market,code,now.timestamp())
            if not fresh:continue
            if m._buy_one(market,it,'SCALP',session,now):
                if market=='KR':
                    with m._NAMUH_VI_LOCK:state.pop(code,None)
                    persist()
                break
    m.trade_scalp=trade_scalp
