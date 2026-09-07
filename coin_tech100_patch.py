from __future__ import annotations

import threading
import time
from collections import deque

DAILY_TTL=300.0
_LOCK=threading.RLock();_CACHE={};_EXEC={};_STARTED=False


def _clamp(v,lo=0.0,hi=100.0):
    try:x=float(v or 0)
    except Exception:x=0.0
    return max(lo,min(hi,x))


def _points_by_ratio(r):
    r=float(r or 0)
    if r>=2.0:return 15.0
    if r>=1.5:return 13.0
    if r>=1.2:return 11.0
    if r>=1.0:return 9.0
    if r>=0.8:return 7.0
    if r>=0.6:return 5.0
    return max(0.0,r/0.6*5.0)


def _exec_points(v):
    v=float(v or 0)
    if v>=110:return 20.0
    if v>=105:return 16.0
    if v>=100:return 14.0
    if v>=95:return 10.0
    if v>=90:return 6.0
    return 0.0


def _record_exec(sym,v,now=None):
    now=float(now or time.time());sym=str(sym).upper()
    with _LOCK:
        h=_EXEC.setdefault(sym,deque(maxlen=120))
        if not h or now-h[-1][0]>=4.5:h.append((now,float(v or 0)))
        return list(h)


def _net_rise(sym,current,seconds,floor,now=None):
    now=float(now or time.time());h=_record_exec(sym,current,now)
    target=now-float(seconds);past=[(ts,v) for ts,v in h if ts<=target]
    if not past:return False,f'체결강도 {floor:.0f}+ · {seconds}초 추세 축적 중'
    start=float(past[-1][1]);end=float(current or 0)
    if start<floor:return False,f'체결강도 시작값 {start:.1f} < {floor:.0f}'
    if end>start:return True,f'체결강도 {seconds}초 순상승 {start:.1f}→{end:.1f}'
    return False,f'체결강도 {seconds}초 상승 대기 {start:.1f}→{end:.1f}'


def _exec_gate(sym,v,now=None):
    v=float(v or 0);_record_exec(sym,v,now)
    if v>=110:return True,'체결강도 110+ · 20/20 즉시 통과'
    if v>=105:return True,'체결강도 105+ · 16/20 즉시 통과'
    if v>=100:return True,'체결강도 100+ · 14/20 즉시 통과'
    if v>=95:return _net_rise(sym,v,30,95.0,now)
    if v>=90:return _net_rise(sym,v,60,90.0,now)
    return False,'체결강도 90 미만 · 미진입'


def _live_bars(bars,q):
    out=[dict(x) for x in list(bars or [])]
    if out and float(getattr(q,'price',0) or 0)>0:
        p=float(q.price);out[-1]['close']=p
        try:out[-1]['high']=max(float(out[-1].get('high') or p),p);out[-1]['low']=min(float(out[-1].get('low') or p),p)
        except Exception:pass
        if float(getattr(q,'quote_volume',0) or 0)>0:out[-1]['quote_volume']=float(q.quote_volume)
    return out


def _daily20(bars):
    if len(bars)<2:return 0.0,None
    prev=bars[-2];today=bars[-1]
    ph=float(prev.get('high') or 0);pl=float(prev.get('low') or 0);pc=float(prev.get('close') or 0);to=float(today.get('open') or 0)
    if ph<=0 or pl<=0 or to<=0:return 0.0,None
    mid=(ph+pl)/2.0;pts=0.0
    if to>=mid:
        pts=12.0;dist=(to/mid-1.0)*100.0;pts+=min(4.0,max(0.0,dist/2.0*4.0))
    else:
        gap=(mid-to)/mid*100.0;pts=max(0.0,4.0-gap/2.0*4.0)
    if pc>0 and to>=pc:pts+=2.0
    if to>=ph:pts+=2.0
    return round(_clamp(pts,0,20),1),{'prev_high':ph,'prev_low':pl,'prev_close':pc,'mid':mid,'today_open':to}


def _volume15(bars,q):
    if len(bars)<2:return 0.0,0.0
    prev=float(bars[-2].get('quote_volume') or 0);cur=float(getattr(q,'quote_volume',0) or bars[-1].get('quote_volume') or 0)
    if prev<=0 or cur<=0:return 0.0,0.0
    ratio=cur/prev
    return round(_points_by_ratio(ratio),1),round(ratio,2)


def apply(ns):
    global _STARTED
    core=ns.get('core');tech_fn=ns.get('_coin_technical_from_bars')
    if core is None or not callable(tech_fn) or getattr(core,'_COIN_TECH100_APPLIED',False):return
    core._COIN_TECH100_APPLIED=True

    def refresh_symbol(symbol):
        symbol=str(symbol or '').upper();now=time.time()
        with _LOCK:
            r=_CACHE.setdefault(symbol,{})
            if r.get('busy') or (r.get('bars') and now-float(r.get('at') or 0)<DAILY_TTL):return
            r['busy']=True
        try:
            try:bars=core.coin_feed.chart(symbol,'1d',50)
            except Exception:bars=[]
            with _LOCK:_CACHE.setdefault(symbol,{}).update(bars=list(bars or []),at=time.time())
        finally:
            with _LOCK:_CACHE.setdefault(symbol,{})['busy']=False

    def refresh_loop():
        while True:
            try:
                for q in core.coin_feed.top_quotes(40):refresh_symbol(q.symbol);time.sleep(.04)
            except Exception:pass
            time.sleep(8)

    def tech45(bars):
        try:d=dict(tech_fn(list(bars or [])) or {})
        except Exception:return 0.0,0.0,[]
        if not d.get('ready'):return 0.0,0.0,list(d.get('components') or [])
        pct=_clamp(float(d.get('raw') or 0)/85.0*100.0)
        return round(pct*.45,1),round(pct,1),list(d.get('components') or [])

    def candidates(n=20):
        n=max(1,min(80,int(n or 20)));ranked=core.coin_feed.top_quotes(max(core.coin_feed.top_n,n));now=time.time();out=[]
        try:settings=core._coin_settings_snapshot();entry=float(settings.get('entry_score',66) or 66)
        except Exception:entry=66.0
        for q in ranked:
            sym=str(q.symbol).upper();_record_exec(sym,q.volume_power,now)
            with _LOCK:r=dict(_CACHE.get(sym) or {})
            if not r.get('bars'):
                refresh_symbol(sym)
                with _LOCK:r=dict(_CACHE.get(sym) or {})
            bars=_live_bars(r.get('bars') or [],q)
            d20,dmeta=_daily20(bars);v15,vratio=_volume15(bars,q);e20=_exec_points(q.volume_power);eok,ereason=_exec_gate(sym,q.volume_power,now)
            t45,tpct,tbreak=tech45(bars);score=round(_clamp(d20+v15+e20+t45,0,100),1);ready=bool(eok and score>=entry)
            age=max(0.0,now-float(q.updated_at or 0)) if q.updated_at else 9999.0
            out.append({'market':'COIN','code':sym,'name':q.name or sym,'price':q.price,'change_pct':q.change_pct,
                'quote_volume':q.quote_volume,'target_volume':q.target_volume,'volume_power':q.volume_power,'execution_strength':q.volume_power,
                'spread_pct':q.spread_pct,'book_imbalance':q.book_imbalance,'score':score,'score_total':score,'technical_score':t45,
                'technical_score_100':tpct,'daily_score':d20,'minute_score':None,'recipe_score':round(d20+v15+e20,1),
                'score_model':'COIN_D20_V15_E20_T45','recipe_weights':{'daily':20,'volume':15,'execution':20,'technical':45},
                'score_components':{'daily20':d20,'volume15':v15,'execution20':e20,'technical45':t45},
                'score_breakdown':[{'key':'daily','label':'일봉','score':d20,'max':20},{'key':'volume','label':'거래량','score':v15,'max':15},
                                   {'key':'execution','label':'체결강도','score':e20,'max':20},{'key':'technical','label':'기술','score':t45,'max':45}],
                'technical_breakdown':tbreak,'daily_reference':dmeta,'volume_ratio':vratio,'daily_gate_pass':True,'volume_gate_pass':True,
                'execution_gate_pass':bool(eok),'minute_gate_pass':True,'technical_gate_pass':True,'entry_gate_pass':ready,'recipe_gate':ready,
                'technical_ready':bool(tpct>0),'entry_gate_stage':('진입조건 통과' if ready else (ereason if not eok else f'총점 {score:.1f} < 진입 {entry:.0f}')),
                'entry_gate':{'order':['daily20','volume15','execution20','technical45'],'execution_rule':'110/105/100 immediate; 95 30s rise; 90 60s rise; <90 block','score_min':entry,'pass':ready},
                'reasons':[f'코인 100 · 일봉 {d20:.1f}/20 + 거래량 {v15:.1f}/15 + 체결 {e20:.1f}/20 + 기술 {t45:.1f}/45',
                           (f"일봉 오늘 시가 {'≥' if dmeta and dmeta['today_open']>=dmeta['mid'] else '<'} 전일(고가+저가)/2" if dmeta else '일봉 데이터 축적 중'),
                           f'거래량 전일비 {vratio:.2f}배 · {v15:.1f}/15',f'{ereason}',f'기술 {tpct:.1f}/100 → {t45:.1f}/45','뉴스·공시·섹터·프로그램 점수 없음 · 1분봉 Gate 없음'],
                'fresh_age':round(age,1),'updated_at':q.updated_at})
        out.sort(key=lambda x:float(x.get('score') or 0),reverse=True);return out[:n]

    core.coin_feed.candidates=candidates
    v33=ns.get('v33')
    def entries_enabled():
        try:return bool(v33._entries_enabled())
        except Exception:return bool(getattr(core,'AUTO_TRADING_ENABLED',True))
    def save_control():
        try:v33._save_control()
        except Exception:pass

    def coin_loop():
        core.COIN_LOOP_STATE['started_at']=time.time();last=0.0
        while True:
            core.COIN_LOOP_STATE['last_tick']=time.time();core.COIN_LOOP_STATE['iterations']+=1
            try:
                items=candidates(50);mp={str(x.get('code') or '').upper():x for x in items};changed=False
                for p in list(core.coin_paper.positions.values()):
                    q=core.coin_feed.quote(p.symbol)
                    if not q or q.price<=0:continue
                    core.coin_paper.mark(p.symbol,q.price);it=mp.get(str(p.symbol).upper());sc=float(it.get('score') or 0) if it else None;reason=''
                    if p.pnl_pct>=3:reason='목표수익 +3% 도달'
                    elif p.pnl_pct<=-1.5:reason='손절 기준 도달'
                    elif sc is not None and sc<46:reason='AI 점수 이탈'
                    if reason and core.coin_paper.sell(p.symbol,q.price,reason):core.COIN_COOLDOWN[p.symbol]=time.time();changed=True
                st=core._coin_settings_snapshot();entry=float(st.get('entry_score',66) or 66)
                if entries_enabled() and st.get('auto_trade_enabled',True):
                    for it in items:
                        if float(it.get('score') or 0)<entry:break
                        if not it.get('entry_gate_pass'):continue
                        sym=str(it.get('code') or '').upper()
                        if not sym or f'COIN:{sym}' in core.coin_paper.positions:continue
                        if float(it.get('fresh_age',9999) or 9999)>30:continue
                        if time.time()-float(core.COIN_COOLDOWN.get(sym,0) or 0)<300:continue
                        q=core.coin_feed.quote(sym);avail=core._coin_available_budget();budget=core._coin_effective_budget()
                        if not q or q.price<=0 or avail<10000:continue
                        if core.coin_paper.buy(q,min(avail,max(10000.0,budget*.20)),'COIN_D20_V15_E20_T45'):changed=True;break
                if changed:core._persist_coin();core._persist_coin_settings()
                if time.time()-last>=60:core._persist_coin();core._persist_coin_settings();save_control();last=time.time()
                core.COIN_LOOP_STATE['last_ok']=time.time();core.COIN_LOOP_STATE['last_error']=''
            except Exception as exc:
                core.COIN_LOOP_STATE['last_error']=str(exc)[:300];print('COIN 20/15/20/45 LOOP ERROR:',exc,flush=True)
            time.sleep(core.AUTO_LOOP_SECONDS)
    core.coin_trade_loop=coin_loop
    core._coin_tech100_thresholds={'score':'daily20+volume15+execution20+technical45','minute_gate':False,'news':False,'sector':False,'program':False}
    if not _STARTED:_STARTED=True;threading.Thread(target=refresh_loop,daemon=True).start()
    print('COIN RECIPE active: daily20 + volume15 + execution20 + technical45; news/sector/program/1m gate OFF',flush=True)
