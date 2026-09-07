from __future__ import annotations

import time
from datetime import datetime
from zoneinfo import ZoneInfo


def _clamp(v,lo=0.0,hi=100.0):
    try:x=float(v or 0)
    except Exception:x=0.0
    return max(lo,min(hi,x))


def _volume15(core,q,market):
    cur=float(getattr(q,'volume',0) or 0);prev=float(getattr(q,'prev_day_volume',0) or 0)
    if cur<=0 or prev<=0:return 0.0,0.0
    market=str(market or '').upper()
    if market=='US':
        now=datetime.now(ZoneInfo('America/New_York'));mins=now.hour*60+now.minute
        if 570<=mins<=960:expected=max(1/390,min(1.0,(mins-570)/390.0))
        elif mins<570:expected=0.03
        else:expected=1.0
    else:
        now=datetime.now(core.KST);mins=now.hour*60+now.minute
        if 540<=mins<=930:expected=max(1/390,min(1.0,(mins-540)/390.0))
        elif mins<540:expected=0.03
        else:expected=1.0
    pace=(cur/prev)/expected
    if pace>=2.0:pts=15.0
    elif pace>=1.5:pts=13.0
    elif pace>=1.2:pts=11.0
    elif pace>=1.0:pts=9.0
    elif pace>=0.8:pts=7.0
    elif pace>=0.6:pts=5.0
    else:pts=max(0.0,pace/0.6*5.0)
    return round(pts,1),round(pace,2)


def apply(ns):
    core=ns.get('core') if isinstance(ns,dict) else None
    if core is None or getattr(core,'_NAMUH_US_KR_RECIPE_SYNC',False):return
    core._NAMUH_US_KR_RECIPE_SYNC=True

    import namuh_recipe8020_patch as recipe
    import namuh_execution_exit_patch as rules

    # Overseas current quote can expose an execution-strength/volume-power field.
    # Parse it when present so the US recipe uses the same execution rule as KR.
    old_apply_us=getattr(core.feed,'_apply_us',None)
    if callable(old_apply_us):
        try:
            from nhfeed import pick
            def apply_us(code,data):
                old_apply_us(code,data)
                try:
                    strength=pick(data,('cttr','volpower','execution_strength','volume_power'))
                    if strength>0:core.feed.q('US',code).update_execution(strength)
                except Exception:pass
            core.feed._apply_us=apply_us
        except Exception as exc:print('US EXEC PARSER PATCH ERROR:',exc,flush=True)

    old_candidate=core.candidate
    def candidate(q,market,smart=False,secmap=None,stockmap=None,leadermap=None,sector_rankmap=None,now=None):
        out=old_candidate(q,market,smart,secmap,stockmap,leadermap,sector_rankmap,now)
        market=str(market or '').upper()
        if smart or market!='US' or not isinstance(out,dict):return out

        daily20,dmeta=rules._daily20_from_open(core,q,recipe)
        volume15,pace=_volume15(core,q,market)
        strength=float(getattr(q,'execution_strength',0) or 0)
        exec20=round(_clamp(rules._execution_points(strength),0,20),1)
        exec_ok,exec_reason=rules.execution_gate(q)
        program15,program_ratio=recipe._program15(q)
        event_score=float(getattr(q,'event_score',0) or 0)
        news5=round(_clamp(event_score/10.0*5.0,0,5),1)
        sector_raw=float((secmap or {}).get(core.sector_name(q,market),out.get('sector_score',0)) or 0)
        sector5=round(_clamp(sector_raw/10.0*5.0,0,5),1)
        tech20,tech_breakdown=recipe._technical20(q)
        recipe80=round(daily20+volume15+exec20+program15+news5+sector5,1)
        total=round(_clamp(recipe80+tech20,0,100),1)

        blocked=bool(getattr(q,'event_blocked',False))
        try:blocked=blocked or any(bool(x.get('blocked')) for x in list(getattr(q,'events',[]) or []) if isinstance(x,dict))
        except Exception:pass
        out['score']=0.0 if blocked else total;out['priority_score']=out['score']
        out['score_model']='RECIPE80+TECH20';out['recipe_score']=recipe80;out['technical_score']=tech20
        out['technical_breakdown']=tech_breakdown;out['entry_gate_pass']=bool(not blocked and exec_ok and total>=72.0)
        out['execution_gate_pass']=bool(exec_ok);out['execution_gate_reason']=str(exec_reason)
        out['minute_gate_pass']=True;out['orderbook_gate_pass']=True;out['daily_gate_pass']=True;out['technical_gate_pass']=True
        out['score_components']={'recipe80':recipe80,'technical20':tech20,'daily20':daily20,'volume15':volume15,
                                 'execution20':exec20,'program15':program15,'news5':news5,'sector_flow5':sector5}
        out['daily_reference']=dmeta;out['volume_pace']=pace;out['program_ratio_pct']=program_ratio;out['minute_score']=None
        out['reasons']=[
            f'레시피 {recipe80:.1f}/80 + 기술 {tech20:.1f}/20 = {total:.1f}/100',
            (f"일봉 {daily20:.1f}/20 · 오늘 시가 {'≥' if dmeta and dmeta['today_open']>=dmeta['mid'] else '<'} 전일(고가+저가)/2" if dmeta else '일봉 데이터 대기 · 0/20'),
            f'거래량 {volume15:.1f}/15 · 장중속도 {pace:.2f}배',f'{exec_reason} · {exec20:.1f}/20',
            f'프로그램 {program15:.1f}/15 · 공시/호재 {news5:.1f}/5 · 섹터 {sector5:.1f}/5',
            f"기술 {tech20:.1f}/20 · MA {tech_breakdown.get('MA',0):.1f} RSI {tech_breakdown.get('RSI',0):.1f} MACD {tech_breakdown.get('MACD',0):.1f}",
            '국장과 동일 단타 레시피 · 1분봉 진입조건 없음']
        return out
    core.candidate=candidate

    # US final freshness/gate: price freshness + the same execution rule only.
    old_status=core.feed.entry_data_status;refresh_at={}
    def entry_data_status(market,code,now_ts=None):
        market=str(market or '').upper();now_ts=float(now_ts or time.time())
        if market!='US':return old_status(market,code,now_ts)
        code=str(code).upper();q=core.feed.quotes_for('US').get(code)
        stale=(not q or float(getattr(q,'price',0) or 0)<=0 or now_ts-float(getattr(q,'updated_at',0) or 0)>20)
        if stale and now_ts-float(refresh_at.get(code,0) or 0)>=5:
            refresh_at[code]=now_ts
            try:
                from nhplug import call
                data=call('/gbstock/quote/v1/current',{'iem_cd':code});core.feed._apply_us(code,data)
            except Exception:pass
            q=core.feed.quotes_for('US').get(code)
        if not q or float(getattr(q,'price',0) or 0)<=0:return False,'현재가 미수신'
        if now_ts-float(getattr(q,'updated_at',0) or 0)>25:return False,'현재가 25초 초과'
        ok,reason=rules.execution_gate(q,now_ts)
        if not ok:return False,str(reason)
        return True,'정상(국장 동일 체결강도 Gate)'
    core.feed.entry_data_status=entry_data_status

    # US scalp is day-trade as well: flatten just before the regular close.
    old_sell=core.mark_and_sell
    def mark_and_sell(market,scalp,smart,now=None):
        now=(now or core.datetime.now(core.KST)).astimezone(core.KST)
        if str(market).upper()=='US':
            ny=now.astimezone(ZoneInfo('America/New_York'));mins=ny.hour*60+ny.minute
            if ny.weekday()<5 and mins>=15*60+59:
                qs=core.feed.quotes_for('US');fx=core._fx('US');sold=False
                for p in list(core.paper.market_positions('US')):
                    q=qs.get(p.code);px=float(getattr(q,'price',0) or getattr(p,'current_price',0) or getattr(p,'avg_price',0) or 0)
                    if px<=0:continue
                    try:core.paper.mark('US',p.code,px,fx)
                    except Exception:pass
                    if core.paper.sell('US',p.code,px,fx,'US 15:59 ET 장마감 전 강제청산'):sold=True
                if sold:
                    try:core._persist_paper()
                    except Exception:pass
        return old_sell(market,scalp,smart,now)
    core.mark_and_sell=mark_and_sell

    old_trade=core.trade_scalp
    def trade_scalp(market,candidates,now=None):
        if str(market).upper()=='US':
            dt=(now or core.datetime.now(core.KST)).astimezone(ZoneInfo('America/New_York'))
            if dt.weekday()<5 and dt.hour*60+dt.minute>=15*60+59:return
        return old_trade(market,candidates,now)
    core.trade_scalp=trade_scalp

    try:
        old_health=core.health_payload
        def health():
            d=dict(old_health());us=list(core.feed.quotes_for('US').values())
            d['stock_scalp_recipe_markets']=['KR','US'];d['us_scalp_score_model']='RECIPE80+TECH20'
            d['us_execution_strength_ready']=sum(1 for q in us if float(getattr(q,'execution_strength',0) or 0)>0)
            d['us_force_exit']='15:59 ET';return d
        core.health_payload=health
    except Exception:pass
    print('NAMUH CROSSMARKET active: US=KR RECIPE80+TECH20 + same EXEC gate; US 15:59 ET force exit',flush=True)
