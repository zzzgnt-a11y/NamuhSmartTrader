from __future__ import annotations
import threading,time

DAILY_MIN=45.0
EXEC_MIN=100.0
MINUTE_MIN=55.0
DAILY_TTL=900.0
MINUTE_TTL=30.0
_LOCK=threading.RLock();_CACHE={};_STARTED=False

def _clamp(v):
    try:v=float(v or 0)
    except Exception:v=0.0
    return max(0.0,min(100.0,v))

def apply(ns):
    global _STARTED
    core=ns.get('core'); tech_fn=ns.get('_coin_technical_from_bars')
    if core is None or not callable(tech_fn) or getattr(core,'_COIN_TECH100_APPLIED',False):return
    core._COIN_TECH100_APPLIED=True

    def frame_score(bars):
        try:d=dict(tech_fn(list(bars or [])) or {})
        except Exception:return None,[]
        if not d.get('ready'):return None,list(d.get('components') or [])
        return round(_clamp(float(d.get('raw') or 0)/85.0*100.0),1),list(d.get('components') or [])

    def refresh_symbol(symbol):
        symbol=str(symbol or '').upper(); now=time.time()
        with _LOCK:
            r=_CACHE.setdefault(symbol,{})
            if r.get('busy'):return
            dd=now-float(r.get('daily_at') or 0)>=DAILY_TTL
            md=now-float(r.get('minute_at') or 0)>=MINUTE_TTL
            if not dd and not md:return
            r['busy']=True
        try:
            if dd:
                try:s,b=frame_score(core.coin_feed.chart(symbol,'1d',80))
                except Exception:s,b=None,[]
                with _LOCK:r=_CACHE.setdefault(symbol,{});r.update(daily_score=s,daily_breakdown=b,daily_at=time.time())
            if md:
                try:s,b=frame_score(core.coin_feed.chart(symbol,'1m',120))
                except Exception:s,b=None,[]
                with _LOCK:r=_CACHE.setdefault(symbol,{});r.update(minute_score=s,minute_breakdown=b,minute_at=time.time())
        finally:
            with _LOCK:_CACHE.setdefault(symbol,{})['busy']=False

    def refresh_loop():
        while True:
            try:
                for q in core.coin_feed.top_quotes(30):
                    refresh_symbol(q.symbol);time.sleep(.05)
            except Exception:pass
            time.sleep(5)

    def candidates(n=20):
        n=max(1,min(80,int(n or 20))); ranked=core.coin_feed.top_quotes(max(core.coin_feed.top_n,n)); now=time.time();out=[]
        for q in ranked:
            sym=str(q.symbol).upper()
            with _LOCK:r=dict(_CACHE.get(sym) or {})
            ds=r.get('daily_score');ms=r.get('minute_score');vp=float(q.volume_power or 0)
            dr=ds is not None;mr=ms is not None;dp=bool(dr and float(ds)>=DAILY_MIN);ep=vp>=EXEC_MIN;mp=bool(mr and float(ms)>=MINUTE_MIN)
            ready=dr and mr;score=round(_clamp(.65*float(ds)+.35*float(ms)),1) if ready else 0.0;gate=bool(dp and ep and mp)
            if not dr:stage='1 일봉 데이터 대기'
            elif not dp:stage=f'1 일봉 {float(ds):.0f}점 미달'
            elif not ep:stage=f'2 체결강도 {vp:.0f} 미달'
            elif not mr:stage='3 1분봉 데이터 대기'
            elif not mp:stage=f'3 1분봉 {float(ms):.0f}점 미달'
            else:stage='1→2→3 진입조건 통과'
            age=max(0.0,now-float(q.updated_at or 0)) if q.updated_at else 9999.0
            out.append({'market':'COIN','code':sym,'name':q.name or sym,'price':q.price,'change_pct':q.change_pct,'quote_volume':q.quote_volume,'target_volume':q.target_volume,'volume_power':q.volume_power,'execution_strength':q.volume_power,'spread_pct':q.spread_pct,'book_imbalance':q.book_imbalance,'score':score,'score_total':score,'technical_score':score,'technical_score_100':score,'value_score':0.0,'daily_score':None if ds is None else round(float(ds),1),'minute_score':None if ms is None else round(float(ms),1),'recipe_score':score,'score_model':'TECH100','recipe_weights':{'daily':65,'minute':35},'score_components':{'technical100':score,'daily65':round(float(ds or 0)*.65,1),'minute35':round(float(ms or 0)*.35,1)},'score_breakdown':[{'key':'daily','label':'일봉 65%','score':round(float(ds or 0)*.65,1),'max':65},{'key':'minute','label':'1분봉 35%','score':round(float(ms or 0)*.35,1),'max':35}],'technical_breakdown':[{'key':'daily','label':'일봉 점수','score':round(float(ds or 0),1),'max':100},{'key':'minute','label':'1분봉 점수','score':round(float(ms or 0),1),'max':100}],'daily_breakdown':list(r.get('daily_breakdown') or []),'minute_breakdown':list(r.get('minute_breakdown') or []),'daily_gate_pass':dp,'execution_gate_pass':ep,'minute_gate_pass':mp,'entry_gate_pass':gate,'entry_gate_stage':stage,'entry_gate':{'order':['daily','execution_strength','minute'],'daily_min':DAILY_MIN,'execution_min':EXEC_MIN,'minute_min':MINUTE_MIN,'daily_pass':dp,'execution_pass':ep,'minute_pass':mp,'pass':gate},'technical_ready':ready,'recipe_gate':gate,'recipe_fallback':not ready,'reasons':['TECH100 · 일봉65% + 1분봉35%',f"1 일봉 {'대기' if ds is None else f'{float(ds):.0f}점'} · {'통과' if dp else '미달'}",f"2 체결강도 {vp:.0f} · {'통과' if ep else '미달'}",f"3 1분봉 {'대기' if ms is None else f'{float(ms):.0f}점'} · {'통과' if mp else '미달'}",stage],'fresh_age':round(age,1),'updated_at':q.updated_at})
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
                items=candidates(50);mp0={str(x.get('code') or '').upper():x for x in items};changed=False
                for p in list(core.coin_paper.positions.values()):
                    q=core.coin_feed.quote(p.symbol)
                    if not q or q.price<=0:continue
                    core.coin_paper.mark(p.symbol,q.price);it=mp0.get(str(p.symbol).upper());sc=float(it.get('score') or 0) if it and it.get('technical_ready') else None;reason=''
                    if p.pnl_pct>=3:reason='목표수익 +3% 도달'
                    elif p.pnl_pct<=-1.5:reason='손절 기준 도달'
                    elif sc is not None and sc<46:reason='기술 AI 점수 이탈'
                    if reason and core.coin_paper.sell(p.symbol,q.price,reason):core.COIN_COOLDOWN[p.symbol]=time.time();changed=True
                st=core._coin_settings_snapshot()
                if entries_enabled() and st.get('auto_trade_enabled',True):
                    entry=float(st.get('entry_score',66) or 66)
                    for it in items:
                        if float(it.get('score') or 0)<entry:break
                        if not it.get('entry_gate_pass'):continue
                        sym=str(it.get('code') or '').upper()
                        if not sym or f'COIN:{sym}' in core.coin_paper.positions:continue
                        if float(it.get('fresh_age',9999) or 9999)>30:continue
                        if time.time()-float(core.COIN_COOLDOWN.get(sym,0) or 0)<300:continue
                        q=core.coin_feed.quote(sym);avail=core._coin_available_budget();budget=core._coin_effective_budget()
                        if not q or q.price<=0 or avail<10000:continue
                        if core.coin_paper.buy(q,min(avail,max(10000.0,budget*.20)),'COIN_TECH100'):changed=True;break
                if changed:core._persist_coin();core._persist_coin_settings()
                if time.time()-last>=60:core._persist_coin();core._persist_coin_settings();save_control();last=time.time()
                core.COIN_LOOP_STATE['last_ok']=time.time();core.COIN_LOOP_STATE['last_error']=''
            except Exception as exc:
                core.COIN_LOOP_STATE['last_error']=str(exc)[:300];print('COIN TECH100 LOOP ERROR:',exc,flush=True)
            time.sleep(core.AUTO_LOOP_SECONDS)
    core.coin_trade_loop=coin_loop
    core._coin_tech100_thresholds={'daily_min':DAILY_MIN,'execution_min':EXEC_MIN,'minute_min':MINUTE_MIN,'score':'daily65+minute35'}
    if not _STARTED:
        _STARTED=True;threading.Thread(target=refresh_loop,daemon=True).start()
