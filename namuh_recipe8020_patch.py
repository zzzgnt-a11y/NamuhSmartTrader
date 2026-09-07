from __future__ import annotations

from datetime import datetime
import time

from engine import execution_gate as _execution_gate


def _clamp(v, lo=0.0, hi=100.0):
    try:
        x=float(v or 0)
    except Exception:
        x=0.0
    return max(lo,min(hi,x))


def _completed_prev_bar(core,q):
    bars=list(getattr(q,'daily_bars',[]) or [])
    if not bars:return None
    today=datetime.now(core.KST).strftime('%Y%m%d')
    completed=[]
    for b in bars:
        d=str(b.get('date') or '').replace('-','').replace('/','')
        if len(d)==8 and d<today:
            completed.append(b)
    if completed:return completed[-1]
    return bars[-2] if len(bars)>=2 else bars[-1]


def _daily20(core,q):
    b=_completed_prev_bar(core,q)
    if not b:return 0.0,None
    o=float(b.get('open') or 0);c=float(b.get('close') or 0);h=float(b.get('high') or 0);p=float(getattr(q,'price',0) or 0)
    if o<=0 or c<=0 or p<=0:return 0.0,None
    mid=(o+c)/2.0
    pts=0.0
    if p>=mid:
        pts=12.0
        dist=(p/mid-1.0)*100.0
        pts+=min(4.0,max(0.0,dist/2.0*4.0))
    else:
        gap=(mid-p)/mid*100.0
        pts=max(0.0,4.0-gap/2.0*4.0)
    if p>=c:pts+=2.0
    if h>0 and p>=h:pts+=2.0
    return round(_clamp(pts,0,20),1),{'prev_open':o,'prev_close':c,'prev_high':h,'mid':mid,'price':p}


def _volume15(core,q):
    cur=float(getattr(q,'volume',0) or 0);prev=float(getattr(q,'prev_day_volume',0) or 0)
    if cur<=0 or prev<=0:return 0.0,0.0
    now=datetime.now(core.KST);mins=now.hour*60+now.minute
    if 540<=mins<=930:
        elapsed=max(1,mins-540)
        expected=max(1/390,min(1.0,elapsed/390.0))
    elif mins<540:
        expected=0.03
    else:
        expected=1.0
    pace=(cur/prev)/expected
    if pace>=2.0:pts=15.0
    elif pace>=1.5:pts=13.0
    elif pace>=1.2:pts=11.0
    elif pace>=1.0:pts=9.0
    elif pace>=0.8:pts=7.0
    elif pace>=0.6:pts=5.0
    else:pts=max(0.0,pace/0.6*5.0)
    return round(pts,1),round(pace,2)


def _execution20(q,market):
    s=float(getattr(q,'execution_strength',0) or 0)
    if market!='KR':return 0.0,True,'미장 체결강도 점수 미사용'
    if s>=110:pts=20.0
    elif s>=105:pts=17.0
    elif s>=100:pts=14.0
    elif s>=95:pts=11.0
    elif s>=90:pts=8.0
    else:pts=max(0.0,(s-70.0)/20.0*8.0)
    try:ok,reason=_execution_gate(q)
    except Exception:ok,reason=False,'체결강도 확인 대기'
    return round(_clamp(pts,0,20),1),bool(ok),str(reason or '')


def _program15(q):
    net=float(getattr(q,'program_net',0) or 0);vol=float(getattr(q,'volume',0) or 0)
    if net<=0 or vol<=0:return 0.0,0.0
    ratio=net/vol*100.0
    if ratio>=10:pts=15.0
    elif ratio>=7:pts=13.0
    elif ratio>=5:pts=11.0
    elif ratio>=3:pts=9.0
    elif ratio>=1:pts=6.0
    else:pts=max(1.0,ratio)
    return round(pts,1),round(ratio,2)


def _ema(values,period):
    vals=[float(x) for x in values if float(x or 0)>0]
    if not vals:return 0.0
    k=2.0/(period+1.0);e=vals[0]
    for x in vals[1:]:e=x*k+e*(1.0-k)
    return e


def _rsi14(closes):
    if len(closes)<15:return None
    ds=[closes[i]-closes[i-1] for i in range(1,len(closes))][-14:]
    gains=sum(max(x,0.0) for x in ds)/14.0
    losses=sum(max(-x,0.0) for x in ds)/14.0
    if losses<=1e-12:return 100.0
    rs=gains/losses
    return 100.0-(100.0/(1.0+rs))


def _technical20(q):
    """Independent TECH20 from daily OHLC; never depends on 1m/stage30."""
    bars=list(getattr(q,'daily_bars',[]) or [])
    closes=[]
    highs=[]
    lows=[]
    for b in bars[-40:]:
        try:
            c=float(b.get('close') or 0);h=float(b.get('high') or 0);l=float(b.get('low') or 0)
        except Exception:
            continue
        if c>0:
            closes.append(c);highs.append(h or c);lows.append(l or c)
    p=float(getattr(q,'price',0) or (closes[-1] if closes else 0))
    if len(closes)<20 or p<=0:
        return 0.0,{'status':'daily bars <20'}

    # Replace today's partial close with the latest live price when possible.
    closes=list(closes)
    if closes:closes[-1]=p

    # Moving-average trend: 5 points.
    ma5=sum(closes[-5:])/5.0
    ma20=sum(closes[-20:])/20.0
    prev_ma20=sum(closes[-21:-1])/20.0 if len(closes)>=21 else ma20
    ma_pts=(2.0 if p>=ma5 else 0.0)+(2.0 if ma5>=ma20 else 0.0)+(1.0 if ma20>=prev_ma20 else 0.0)

    # RSI: 4 points. Strong-but-not-overheated momentum scores highest.
    rsi=_rsi14(closes)
    if rsi is None:rsi_pts=0.0
    elif 50<=rsi<=70:rsi_pts=4.0
    elif 40<=rsi<50 or 70<rsi<=78:rsi_pts=3.0
    elif 30<=rsi<40:rsi_pts=1.5
    elif rsi>78:rsi_pts=1.0
    else:rsi_pts=0.5

    # MACD: 4 points.
    macd=_ema(closes[-30:],12)-_ema(closes[-30:],26)
    macd_hist=[]
    if len(closes)>=26:
        start=max(26,len(closes)-9)
        for i in range(start,len(closes)+1):
            part=closes[:i]
            macd_hist.append(_ema(part[-30:],12)-_ema(part[-30:],26))
    signal=_ema(macd_hist,9) if macd_hist else 0.0
    macd_pts=(3.0 if macd>=signal else 0.0)+(1.0 if macd>=0 else 0.0)

    # Bollinger position: 3 points.
    win=closes[-20:];mid=sum(win)/20.0
    var=sum((x-mid)**2 for x in win)/20.0
    sd=var**0.5;upper=mid+2*sd;lower=mid-2*sd
    if mid<=p<=upper:bb_pts=3.0
    elif lower<=p<mid:bb_pts=1.5
    elif p>upper:bb_pts=1.0
    else:bb_pts=0.0

    # Price structure: 4 points.
    prev_close=closes[-2] if len(closes)>=2 else p
    prev5_high=max(highs[-6:-1]) if len(highs)>=6 else max(highs[:-1] or [p])
    structure_pts=(2.0 if p>=prev_close else 0.0)+(2.0 if p>=prev5_high else (1.0 if p>=ma20 else 0.0))

    total=round(_clamp(ma_pts+rsi_pts+macd_pts+bb_pts+structure_pts,0,20),1)
    return total,{
        'MA':round(ma_pts,1),'RSI':round(rsi_pts,1),'MACD':round(macd_pts,1),'볼린저':round(bb_pts,1),'가격구조':round(structure_pts,1),
        'rsi':None if rsi is None else round(rsi,1),'ma5':round(ma5,2),'ma20':round(ma20,2),'macd':round(macd,4),'signal':round(signal,4)
    }


def apply(ns):
    core=ns.get('core') if isinstance(ns,dict) else None
    if core is None or getattr(core,'_NAMUH_RECIPE_8020',False):return
    core._NAMUH_RECIPE_8020=True

    old_candidate=core.candidate
    samsung_log=[0.0]
    def candidate(q,market,smart=False,secmap=None,stockmap=None,leadermap=None,sector_rankmap=None,now=None):
        out=old_candidate(q,market,smart,secmap,stockmap,leadermap,sector_rankmap,now)
        if smart or not isinstance(out,dict):return out
        market=str(market or '').upper()
        if market!='KR':
            out['minute_gate_pass']=True
            blocked=bool(getattr(q,'event_blocked',False))
            out['entry_gate_pass']=bool(float(out.get('score',0) or 0)>=72 and not blocked)
            return out

        daily20,dmeta=_daily20(core,q)
        volume15,pace=_volume15(core,q)
        exec20,exec_ok,exec_reason=_execution20(q,market)
        program15,program_ratio=_program15(q)
        event_score=float(getattr(q,'event_score',0) or 0)
        news5=round(_clamp(event_score/10.0*5.0,0,5),1)
        sector_raw=float((secmap or {}).get(core.sector_name(q,market),out.get('sector_score',0)) or 0)
        sector5=round(_clamp(sector_raw/10.0*5.0,0,5),1)
        tech20,tech_breakdown=_technical20(q)
        recipe80=round(daily20+volume15+exec20+program15+news5+sector5,1)
        total=round(_clamp(recipe80+tech20,0,100),1)

        blocked=bool(getattr(q,'event_blocked',False))
        try:blocked=blocked or any(bool(x.get('blocked')) for x in list(getattr(q,'events',[]) or []) if isinstance(x,dict))
        except Exception:pass

        out['score']=0.0 if blocked else total
        out['priority_score']=out['score']
        out['score_model']='RECIPE80+TECH20'
        out['recipe_score']=recipe80
        out['technical_score']=tech20
        out['technical_breakdown']=tech_breakdown
        out['entry_gate_pass']=bool(not blocked and exec_ok and total>=72.0)
        out['execution_gate_pass']=bool(exec_ok)
        out['execution_gate_reason']=exec_reason
        out['minute_gate_pass']=True
        out['orderbook_gate_pass']=True
        out['daily_gate_pass']=True
        out['technical_gate_pass']=True
        out['score_components']={
            'recipe80':recipe80,'technical20':tech20,'daily20':daily20,'volume15':volume15,
            'execution20':exec20,'program15':program15,'news5':news5,'sector_flow5':sector5,
        }
        out['daily_reference']=dmeta
        out['volume_pace']=pace
        out['program_ratio_pct']=program_ratio
        out['minute_score']=None
        out['reasons']=[
            f'레시피 {recipe80:.1f}/80 + 기술 {tech20:.1f}/20 = {total:.1f}/100',
            (f"일봉 {daily20:.1f}/20 · 현재가 {'>' if dmeta and dmeta['price']>=dmeta['mid'] else '<'} 전일(시가+종가)/2" if dmeta else '일봉 데이터 대기 · 0/20'),
            f'거래량 {volume15:.1f}/15 · 장중속도 {pace:.2f}배',
            f'{exec_reason} · {exec20:.1f}/20',
            f'프로그램 순매수 {float(getattr(q,"program_net",0) or 0):,.0f}주 · {program15:.1f}/15',
            f'공시/호재 {news5:.1f}/5 · 섹터수급 {sector5:.1f}/5',
            f"기술 MA {tech_breakdown.get('MA',0):.1f}/5 · RSI {tech_breakdown.get('RSI',0):.1f}/4 · MACD {tech_breakdown.get('MACD',0):.1f}/4 · 볼린저 {tech_breakdown.get('볼린저',0):.1f}/3 · 구조 {tech_breakdown.get('가격구조',0):.1f}/4",
            '1분봉 진입조건 삭제 · 수신 상태만 감시',
        ]
        if str(getattr(q,'code',''))=='005930' and time.time()-samsung_log[0]>=10:
            samsung_log[0]=time.time()
            print(
                f"SAMSUNG SCORE total={out['score']:.1f} recipe={recipe80:.1f} tech={tech20:.1f} "
                f"daily={daily20:.1f} volume={volume15:.1f} exec={exec20:.1f} program={program15:.1f} "
                f"news={news5:.1f} sector={sector5:.1f} price={float(getattr(q,'price',0) or 0):.0f} "
                f"strength={float(getattr(q,'execution_strength',0) or 0):.1f} program_net={float(getattr(q,'program_net',0) or 0):.0f} "
                f"tech_detail={tech_breakdown} entry={bool(out['entry_gate_pass'])}", flush=True)
        return out
    core.candidate=candidate

    base_trade=ns.get('_prev_trade_scalp')
    if callable(base_trade):
        def trade_scalp(market,candidates,now=None):
            rows=[x for x in list(candidates or []) if bool(x.get('entry_gate_pass',False)) and float(x.get('score',0) or 0)>=72.0]
            return base_trade(market,rows,now)
        core.trade_scalp=trade_scalp

    try:
        old_health=core.health_payload
        def health():
            d=dict(old_health())
            q=core.feed.q('KR','005930')
            try:bars=len(list(core.feed.bars('KR','005930','1m') or []))
            except Exception:bars=0
            d['scalp_score_model']='RECIPE80+TECH20'
            d['minute_entry_gate']=False
            d['samsung_1m_bars']=bars
            d['samsung_daily_bars']=len(list(getattr(q,'daily_bars',[]) or []))
            return d
        core.health_payload=health
    except Exception:pass

    print('NAMUH RECIPE PATCH: KR 80 + TECH20 daily-indicator engine active; 1m entry gate removed',flush=True)
