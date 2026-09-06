from __future__ import annotations

from engine import execution_gate as _execution_gate


def _clamp(v, lo=0.0, hi=100.0):
    try:
        x=float(v or 0)
    except Exception:
        x=0.0
    return max(lo,min(hi,x))


def _walk(v):
    if isinstance(v,dict):
        yield v
        for x in v.values():
            yield from _walk(x)
    elif isinstance(v,list):
        for x in v:
            yield from _walk(x)


def _pick(v,keys):
    for o in _walk(v):
        for k in keys:
            if k in o and o[k] not in (None,''):
                try:return float(str(o[k]).replace(',','').replace('+','').strip())
                except Exception:pass
    return 0.0


def _capture_book(q,data):
    ask=_pick(data,('askp1','askp','best_ask','ask_price','ask_prc','seln_prc','ovrs_askp'))
    bid=_pick(data,('bidp1','bidp','best_bid','bid_price','bid_prc','shnu_prc','ovrs_bidp'))
    if ask>0:setattr(q,'best_ask',ask)
    if bid>0:setattr(q,'best_bid',bid)


def _install_daily_parser_fix():
    """NH KR currentDaily uses stck_bsop_date on some responses.

    The legacy parser omitted that key, so perfectly valid daily rows were
    discarded and every candidate stayed in 'daily data waiting'.  Keep the
    existing parser first, then recover any dated OHLC rows from the full
    response tree when it returns nothing.
    """
    try:
        import nhfeed as nh
        if getattr(nh,'_NAMUH_DAILY_PARSER_FIXED',False):return
        nh._NAMUH_DAILY_PARSER_FIXED=True
        old=nh.parse_daily_rows
        def fixed(data,market='KR'):
            rows=old(data,market)
            if rows:return rows
            out=[];seen=set()
            for r in nh.walk(data):
                if not isinstance(r,dict):continue
                d=nh.normalize_date(r.get('stck_bsop_date') or r.get('bsop_date') or r.get('xymd') or r.get('date') or r.get('trade_date'))
                c=nh.num(r.get('stck_clpr') or r.get('stck_prpr') or r.get('ovrs_prpr') or r.get('close_prc') or r.get('close') or r.get('trdprc') or r.get('prpr'))
                if not d or c<=0 or d in seen:continue
                seen.add(d)
                out.append({
                    'date':d,
                    'open':nh.num(r.get('stck_oprc') or r.get('ovrs_oprc') or r.get('open_prc') or r.get('open')) or c,
                    'high':nh.num(r.get('stck_hgpr') or r.get('ovrs_hgpr') or r.get('high_prc') or r.get('high')) or c,
                    'low':nh.num(r.get('stck_lwpr') or r.get('ovrs_lwpr') or r.get('low_prc') or r.get('low')) or c,
                    'close':c,
                    'volume':nh.num(r.get('acml_vol') or r.get('acvol') or r.get('movolume') or r.get('volume') or r.get('vol')),
                })
            out.sort(key=lambda x:x['date'])
            return out
        nh.parse_daily_rows=fixed
        print('NAMUH DATA PATCH: KR daily parser accepts stck_bsop_date',flush=True)
    except Exception as exc:
        print('NAMUH DATA PATCH ERROR:',exc,flush=True)


def _envelope_points(m,q,market):
    try:
        bars=list(m.feed.bars(market,q.code,'1m') or [])
        closes=[float(x.get('close') or 0) for x in bars[-40:] if float(x.get('close') or 0)>0]
    except Exception:
        closes=[]
    if len(closes)<20:
        closes=[float(x) for x in list(getattr(q,'prices',[]) or [])[-40:] if float(x or 0)>0]
    if len(closes)<20:
        return 0.0,None,None,None
    mid=sum(closes[-20:])/20.0
    lower=mid*0.98;upper=mid*1.02;price=float(getattr(q,'price',0) or closes[-1])
    if price<=lower:pts=10.0
    elif price<=mid:pts=10.0-3.0*((price-lower)/max(mid-lower,1e-9))
    elif price<upper:pts=7.0-5.0*((price-mid)/max(upper-mid,1e-9))
    else:pts=max(0.0,2.0-(price-upper)/max(upper,1e-9)*100.0)
    return round(_clamp(pts,0,10),1),round(lower,4),round(mid,4),round(upper,4)


def _technical20(m,q,market,sec_score,stock_score,now):
    try:
        a=m.scalp_analysis(q,float(sec_score or 0),float(stock_score or 0),market,now)
        b=dict(a.get('breakdown') or {})
        raw=sum(float(b.get(k,0) or 0) for k in ('MACD','RSI','볼린저','거래량','이평','가격구조','엘리어트'))
        return round(_clamp(raw/73.0*20.0,0,20),1),b
    except Exception:
        return 0.0,{}


def apply(m):
    if getattr(m,'_NAMUH_SCORE_503020',False):return
    m._NAMUH_SCORE_503020=True
    _install_daily_parser_fix()

    # Capture best ask/bid whenever the existing quote endpoints expose them.
    try:
        feed=m.feed
        old_kr=feed._apply_kr
        def apply_kr(code,data):
            old_kr(code,data);_capture_book(feed.q('KR',code),data)
        feed._apply_kr=apply_kr
        old_us=feed._apply_us
        def apply_us(code,data):
            old_us(code,data);_capture_book(feed.q('US',code),data)
        feed._apply_us=apply_us
    except Exception:
        pass

    old=m.candidate
    def candidate(q,market,smart=False,secmap=None,stockmap=None,leadermap=None,sector_rankmap=None,now=None):
        if smart:
            return old(q,market,True,secmap,stockmap,leadermap,sector_rankmap,now)
        out=old(q,market,False,secmap,stockmap,leadermap,sector_rankmap,now)
        if not isinstance(out,dict):return out
        market=str(market or '').upper()

        # 1st confirmation = 50 points: daily 15 + execution 15 + ask>bid 10 + 1m 10.
        ds=out.get('daily_score');ms=out.get('minute_score')
        # PC minute-sync is durable across Render deploys. If it carries the
        # explicit daily/minute fields, prefer those fresh real values while
        # the new server is rebuilding its in-memory candle cache.
        if market=='KR':
            try:
                sig=m._minute_signal(q.code,True)
                if isinstance(sig,dict):
                    if ds is None and sig.get('daily_score') is not None:ds=float(sig.get('daily_score'))
                    sm=sig.get('minute_score') if sig.get('minute_score') is not None else sig.get('score')
                    if sm is not None and (ms is None or float(ms or 0)<=0) and float(sm)>0:ms=float(sm)
            except Exception:pass
        daily=0.0 if ds is None else _clamp(ds)
        minute=0.0 if ms is None else _clamp(ms)
        daily_pts=round(daily*.15,1)
        minute_pts=round(minute*.10,1)
        daily_ok=ds is not None and daily>=25.0
        minute_ok=ms is not None and minute>=45.0

        strength=float(getattr(q,'execution_strength',0) or 0)
        hist=list(getattr(q,'execution_history',[]) or [])
        exec_available=bool(hist) or (market=='KR' and strength>0)
        if strength>=110:exec_pts=15.0
        elif strength>=100:exec_pts=10.0
        elif strength>=90:exec_pts=6.0
        else:exec_pts=0.0
        if market=='KR':
            try:exec_ok,exec_reason=_execution_gate(q)
            except Exception:exec_ok,exec_reason=False,'체결강도 확인 대기'
        elif exec_available:
            try:exec_ok,exec_reason=_execution_gate(q)
            except Exception:exec_ok,exec_reason=False,'체결강도 확인 대기'
        else:
            # No fabricated US execution strength. Exclude the 15 points and skip only this gate.
            exec_ok=True;exec_reason='미장 체결강도 원천 미지원 · 점수 제외';exec_pts=0.0

        ask=float(getattr(q,'best_ask',0) or 0);bid=float(getattr(q,'best_bid',0) or 0)
        book_ok=ask>0 and bid>0 and ask>bid
        book_pts=10.0 if book_ok else 0.0
        stage50=round(daily_pts+exec_pts+book_pts+minute_pts,1)

        # 2nd confirmation = 30 points: Envelope 10 + technical indicators 20.
        sec=m.sector_name(q,market)
        sec_raw=float((secmap or {}).get(sec,0) or 0);stock_raw=float((stockmap or {}).get(q.code,0) or 0)
        env_pts,env_lo,env_mid,env_hi=_envelope_points(m,q,market)
        tech20,tech_breakdown=_technical20(m,q,market,sec_raw,stock_raw,now)
        stage30=round(env_pts+tech20,1)
        technical_ok=stage30>=12.0

        # 3rd confirmation = 20 points: same-sector relative rise 10 + leading-sector flow 5 + positive news/disclosure 5.
        relative10=round(_clamp(stock_raw/5.0*10.0,0,10),1)
        sectorflow5=round(_clamp(sec_raw/10.0*5.0,0,5),1)
        event_score=float(getattr(q,'event_score',0) or 0)
        news5=round(_clamp(event_score/10.0*5.0,0,5),1)
        stage20=round(relative10+sectorflow5+news5,1)

        blocked=bool(getattr(q,'event_blocked',False))
        try:blocked=blocked or any(bool(x.get('blocked')) for x in list(getattr(q,'events',[]) or []) if isinstance(x,dict))
        except Exception:pass

        total=round(_clamp(stage50+stage30+stage20),1)
        entry_ok=bool(daily_ok and exec_ok and book_ok and minute_ok and technical_ok and not blocked)

        out['score']=0.0 if blocked else total
        out['priority_score']=out['score']
        out['entry_gate_pass']=entry_ok
        out['execution_gate_pass']=bool(exec_ok)
        out['execution_gate_reason']=str(exec_reason or '')
        out['score_model']='50/30/20'
        out['score_components']={
            'stage50':stage50,'stage30':stage30,'stage20':stage20,
            'daily15':daily_pts,'execution15':exec_pts,'orderbook10':book_pts,'minute10':minute_pts,
            'envelope10':env_pts,'technical20':tech20,'sector_relative10':relative10,'sector_flow5':sectorflow5,'news5':news5,
        }
        out['daily_score']=None if ds is None else round(daily,1)
        out['minute_score']=None if ms is None else round(minute,1)
        out['best_ask']=ask or None;out['best_bid']=bid or None
        out['orderbook_gate_pass']=book_ok;out['daily_gate_pass']=daily_ok;out['minute_gate_pass']=minute_ok;out['technical_gate_pass']=technical_ok
        out['envelope']={'lower':env_lo,'mid':env_mid,'upper':env_hi,'points':env_pts}
        out['technical_confirmation']=tech_breakdown
        out['reasons']=[
            f'50/30/20 · 1차 {stage50:.1f}/50 · 기술 {stage30:.1f}/30 · 보조 {stage20:.1f}/20',
            f'일봉 {daily:.0f} → {daily_pts:.1f}/15' if ds is not None else '일봉 데이터 대기 · 0/15',
            f'{exec_reason} → {exec_pts:.1f}/15',
            (f'호가 확인 · 매도 {ask:g} > 매수 {bid:g} → 10/10' if book_ok else '호가 확인 대기/미통과 → 0/10'),
            f'1분봉 {minute:.0f} → {minute_pts:.1f}/10' if ms is not None else '1분봉 데이터 대기 · 0/10',
            f'엔벨로프 {env_pts:.1f}/10 + 기술 {tech20:.1f}/20',
            f'섹터상대 {relative10:.1f}/10 · 주도수급 {sectorflow5:.1f}/5 · 호재 {news5:.1f}/5',
        ]
        return out

    m.candidate=candidate

    # Sequential confirmation is an entry gate for both KR and US, while score remains visible.
    old_trade=m.trade_scalp
    def trade_scalp(market,candidates,now=None):
        rows=[x for x in list(candidates or []) if bool(x.get('entry_gate_pass',False))]
        return old_trade(market,rows,now)
    m.trade_scalp=trade_scalp
