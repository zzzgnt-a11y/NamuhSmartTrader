from __future__ import annotations

import math
import threading
import time


def clamp(v, lo=0.0, hi=100.0):
    try: x=float(v or 0)
    except Exception: x=0.0
    return max(lo,min(hi,x))


def _report(m):
    try: row=m._minute_signal('999999',False)
    except Exception: row=None
    r=row.get('recipe_report') if isinstance(row,dict) else None
    return r if isinstance(r,dict) else {}


def _tech_from_breakdown(a):
    b=(a or {}).get('breakdown',{}) or {}
    raw=sum(float(b.get(k,0) or 0) for k in ('MACD','RSI','볼린저','거래량','이평','가격구조','엘리어트'))
    return round(clamp(raw/73.0*100.0),1)


def _score_bars(m, symbol, bars, market='US', daily=False):
    bars=list(bars or [])
    if len(bars)<20:return None
    try:
        t=m.Quote(str(symbol).upper(),str(symbol).upper(),'')
        last=bars[-1]; t.price=float(last.get('close') or 0)
        if t.price<=0:return None
        t.open=float(last.get('open') or t.price);t.high=float(last.get('high') or t.price);t.low=float(last.get('low') or t.price)
        t.volume=float(last.get('volume') or 0)
        if len(bars)>=2:t.prev_day_volume=float(bars[-2].get('volume') or 0)
        if daily:
            for i,b in enumerate(bars[-60:]):
                t.daily_bars.append({'date':str(b.get('date') or b.get('time') or i),'open':float(b.get('open') or b.get('close') or 0),'high':float(b.get('high') or b.get('close') or 0),'low':float(b.get('low') or b.get('close') or 0),'close':float(b.get('close') or 0),'volume':float(b.get('volume') or 0)})
        for b in bars[-60:]:
            c=float(b.get('close') or 0)
            if c>0:t.prices.append(c)
        return _tech_from_breakdown(m.scalp_analysis(t,0,0,'US'))
    except Exception:return None


def _completed_daily(m,q,market):
    bars=list(getattr(q,'daily_bars',[]) or [])
    if not bars:return []
    try: current=str(m.trading_day_key(market)).replace('-','')
    except Exception: current=''
    out=[]
    for b in bars:
        d=str(b.get('date') or b.get('time') or '').replace('-','').replace('/','')[:8]
        if current and d==current:continue
        out.append(b)
    return out


def _recipe(m,q,market,base):
    daily=_score_bars(m,q.code,_completed_daily(m,q,market),'US',True)
    minute=None; fresh=False
    if market=='KR':
        try:
            r=m._minute_signal(q.code,True)
            if isinstance(r,dict):minute=clamp(float(r.get('score')));fresh=bool(r.get('fresh'))
        except Exception:pass
    if minute is None:
        try:minute=_score_bars(m,q.code,m.feed.bars(market,q.code,'1m'),'US',False)
        except Exception:minute=None
    if minute is None:minute=_tech_from_breakdown(base)
    ready=daily is not None
    recipe=(0.65*daily+0.35*minute) if ready else minute
    floor=None
    try:
        c=_report(m).get('combined') or {}; floor=c.get('recommended_entry_floor')
        floor=float(floor) if floor is not None else None
    except Exception:floor=None
    return {'daily_score':None if daily is None else round(daily,1),'minute_score':round(minute,1),'recipe_score':round(recipe,1),'gate':True if floor is None else recipe>=floor,'gate_floor':floor,'ready':ready,'fresh_minute':fresh,'fallback':not ready or floor is None}


def _exec_points(m,strength):
    try:s=float(strength or 0)
    except Exception:s=0.0
    ex=_report(m).get('execution_strength') or {}
    table=ex.get('point_table') if isinstance(ex,dict) else None
    if isinstance(table,list):
        for row in table:
            try:
                if float(row['min'])<=s<float(row['max_exclusive']):return round(clamp(row['points'],0,10),1),'5Y_CALIBRATED',row.get('bucket')
            except Exception:continue
    pts=0.0 if s<90 else 3.0 if s<100 else 6.0 if s<110 else 10.0
    return pts,'GATE_FALLBACK',None


def apply(m):
    if getattr(m,'_NAMUH_SCORE_4060',False):return
    m._NAMUH_SCORE_4060=True
    old=m.candidate

    def candidate(q,market,smart=False,secmap=None,stockmap=None,leadermap=None,sector_rankmap=None,now=None):
        if smart:return old(q,market,True,secmap,stockmap,leadermap,sector_rankmap,now)
        sec=m.sector_name(q,market);ss=float((secmap or {}).get(sec,0) or 0);stock=float((stockmap or {}).get(q.code,0) or 0)
        a=m.scalp_analysis(q,ss,stock,market,now); r=_recipe(m,q,market,a); tech60=round(clamp(r['recipe_score']*.60,0,60),1)
        b=a.get('breakdown',{}) or {}; ep=None;esrc='UNAVAILABLE';bucket=None
        if market=='KR':
            ep,esrc,bucket=_exec_points(m,getattr(q,'execution_strength',0));flow=clamp(b.get('수급',0),0,10);sector=clamp(ss/10*8,0,8);inside=clamp(stock/5*4,0,4);event=clamp(getattr(q,'event_score',0)/10*8,0,8)
            context=round(ep+flow+sector+inside+event,1);score=0.0 if not a.get('gate',True) else context+tech60
        else:
            # US feed currently has no verified execution-strength field. Do not fabricate 10 points.
            sector=clamp(ss/10*14,0,14);inside=clamp(stock/5*8,0,8);prev=float(getattr(q,'prev_day_volume',0) or 0);vr=float(getattr(q,'volume',0) or 0)/prev*100 if prev>0 else 0;liq=clamp(vr/180*10,0,10);op=float(getattr(q,'open',0) or 0);dm=(float(q.price)/op-1)*100 if op>0 else 0;session=clamp((dm+1)/6*8,0,8);context=round(sector+inside+liq+session,1);score=context+tech60
        leader=(leadermap or {}).get(sec)==q.code;ls=float(getattr(q,'leader_strength',0) or 0);priority=float(score)+(6 if leader else 0)+min(4,ss*.4)+ls*.04
        reasons=list(a.get('reasons') or []);reasons.insert(0,f"40/60 · 실시간 {context:.1f}/40 · 기술 {tech60:.1f}/60")
        if ep is not None:reasons.insert(1,f"체결강도 {float(getattr(q,'execution_strength',0) or 0):.1f} → {ep:.1f}/10")
        bd=dict(a.get('breakdown',{}) or {});bd.update({'실시간40':context,'기술60':tech60,'체결강도10':ep or 0,'일봉분봉레시피':r['recipe_score']})
        vi_trigger=m._namuh_vi_trigger(q.open) if market=='KR' and q.open else None;vi_target=m._namuh_vi_target(vi_trigger) if vi_trigger else None
        return {'market':market,'code':q.code,'name':q.name or q.code,'sector':sec,'currency':'KRW' if market=='KR' else 'USD','price':m.krw(q.price) if market=='KR' else round(float(q.price),4),'open':m.krw(q.open) if market=='KR' else round(float(q.open),4),'score':round(clamp(score),1),'priority_score':round(priority,1),'score_breakdown':bd,'score_components':{'context40':context,'technical60':tech60,'execution10':ep},'phase':a.get('phase',''),'daily_score':r['daily_score'],'minute_score':r['minute_score'],'recipe_score':r['recipe_score'],'recipe_gate':r['gate'],'recipe_gate_floor':r['gate_floor'],'recipe_fallback':r['fallback'],'execution_points':ep,'execution_score_source':esrc,'execution_bucket':bucket,'sector_score':ss,'sector_rank':(sector_rankmap or {}).get(sec),'is_sector_leader':leader,'leader_strength':round(ls,1),'execution_strength':getattr(q,'execution_strength',0),'per':None,'pbr':None,'foreign_net':q.foreign_net if market=='KR' else None,'institution_net':q.institution_net if market=='KR' else None,'program_net':q.program_net if market=='KR' else None,'volume_ratio':round(m._vol_ratio(q),1) if q.prev_day_volume>0 else None,'vi_trigger':vi_trigger,'vi_target':vi_target,'vi_pre':vi_target,'reasons':reasons,'series':[m.krw(x) if market=='KR' else round(float(x),4) for x in list(q.prices)[-24:]],'smart_buy_eligible':None,'smart_close_rank':None,'smart_eligibility_reason':None,'event':q.events[0] if q.events else None,'investor_14d':None}
    m.candidate=candidate
    m._namuh_execution_points=lambda s:_exec_points(m,s)

    # Coin: context40 includes Coinone volume_power as execution10, technical60 uses 65/35 daily→1m.
    original=m.coin_feed.candidates;lock=threading.RLock();cache={}
    def coin_recipe(sym,fallback):
        now=time.time()
        with lock:
            row=cache.get(sym)
            if row and now-row['ts']<300:return dict(row)
        out={'recipe_score':float(fallback),'daily_score':None,'minute_score':None,'fallback':True}
        try:
            ds=_score_bars(m,sym,m.coin_feed.chart(sym,'1d',80),'US',True);ms=_score_bars(m,sym,m.coin_feed.chart(sym,'1m',120),'US',False)
            if ds is not None and ms is not None:out={'recipe_score':.65*ds+.35*ms,'daily_score':ds,'minute_score':ms,'fallback':False}
        except Exception:pass
        out['ts']=now
        with lock:cache[sym]=dict(out)
        return out
    def coin_candidates(n=20):
        raw=list(original(max(n,12)))
        if not raw:return []
        maxv=max(float(x.get('quote_volume',0) or 0) for x in raw) or 1;den=max(1,len(raw)-1);out=[]
        for i,x0 in enumerate(raw):
            x=dict(x0);chg=float(x.get('change_pct',0) or 0);mom=0 if chg<=-2 else clamp((chg+2)/3*24,0,24) if chg<1 else 24+(chg-1)/7*36 if chg<=8 else 60-(chg-8)/7*30 if chg<=15 else 16
            r=coin_recipe(str(x.get('code') or '').upper(),mom) if i<8 else {'recipe_score':mom,'daily_score':None,'minute_score':None,'fallback':True};tech=round(clamp(r['recipe_score']*.6,0,60),1);ep,_s,_b=_exec_points(m,x.get('volume_power'));rank=10*(1-i/den);liq=10*math.sqrt(max(0,float(x.get('quote_volume',0) or 0))/maxv);sp=x.get('spread_pct');spread=5 if sp is None else clamp((.7-float(sp))/.7*5,0,5);imb=clamp((float(x.get('book_imbalance',0) or 0)+20)/60*5,0,5);ctx=round(ep+rank+liq+spread+imb,1)
            x['score']=round(clamp(ctx+tech),1);x['score_components']={'context40':ctx,'technical60':tech,'execution10':ep};x['execution_points']=ep;x['execution_strength']=x.get('volume_power');x['daily_score']=r.get('daily_score');x['minute_score']=r.get('minute_score');x['recipe_score']=round(r['recipe_score'],1);x['recipe_gate']=True;x['recipe_fallback']=r.get('fallback',True);re=list(x.get('reasons') or []);re.insert(0,f"40/60 · 실시간 {ctx:.1f}/40 · 기술 {tech:.1f}/60");re.insert(1,f"체결강도 {float(x.get('volume_power',0) or 0):.1f} → {ep:.1f}/10");x['reasons']=re[:8];out.append(x)
        out.sort(key=lambda z:float(z.get('score',0) or 0),reverse=True);return out[:n]
    m.coin_feed.candidates=coin_candidates
