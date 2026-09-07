from __future__ import annotations

import time


def _meta(nh, data):
    vals=[]
    for k in ('rsp_cd','rt_cd','msg_cd','rsp_msg','msg1','message'):
        v=nh.pick_text(data,(k,))
        if v and f'{k}={v}' not in vals:
            vals.append(f'{k}={v}')
    return ' '.join(vals)[:240] or 'empty/no status fields'


def apply(m):
    feed=getattr(m,'feed',None)
    if feed is None or getattr(feed,'_NAMUH_KR_DAILY_FETCH_FIXED',False):
        return
    feed._NAMUH_KR_DAILY_FETCH_FIXED=True

    import nhfeed as nh
    from nhplug import call

    last_log={}

    def log_once(code, text):
        now=time.time();key=str(code)
        if now-float(last_log.get(key,0) or 0)<60:
            return
        last_log[key]=now
        print(f'KR DAILY {key}: {text}',flush=True)

    def fetch_kr_daily(code,count=30):
        code=str(code or '').strip().upper();count=max(1,int(count or 30))
        errors=[]
        # currentDaily is a KRX historical endpoint in the official sample.
        # Always try KRX first even while the live quote session is NXT.
        order=['KRX']
        try:
            for x in feed._market_order():
                x=str(x or '').upper()
                if x and x not in order:order.append(x)
        except Exception:
            pass
        if 'NXT' not in order:order.append('NXT')

        for market_cd in order:
            try:
                data=call('/krstock/quote/v1/currentDaily',{
                    'market_cd':market_cd,
                    'iem_cd':code,
                    'array_cnt':str(count),
                },timeout=10,raise_on_error=False)
                bars=nh.parse_daily_rows(data,'KR')
                if bars:
                    if code=='005930':
                        log_once(code,f'OK {market_cd} bars={len(bars)} last={bars[-1].get("date","")}')
                    return bars[-count:]
                errors.append(f'{market_cd}: {_meta(nh,data)}')
            except Exception as exc:
                errors.append(f'{market_cd}: {type(exc).__name__} {str(exc)[:160]}')

        log_once(code,' | '.join(errors)[-700:] or 'no bars')
        return []

    feed._fetch_kr_daily=fetch_kr_daily
    print('NAMUH DATA PATCH: resilient KR daily fetch active (KRX first)',flush=True)
