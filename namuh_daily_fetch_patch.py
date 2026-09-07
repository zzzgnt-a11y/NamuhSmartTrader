from __future__ import annotations

import time


def _meta(nh, data):
    vals=[]
    for k in ('rsp_cd','rt_cd','msg_cd','rsp_msg','msg1','message'):
        v=nh.pick_text(data,(k,))
        if v and f'{k}={v}' not in vals:
            vals.append(f'{k}={v}')
    return ' '.join(vals)[:240] or 'empty/no status fields'


def _shape(data):
    try:
        if isinstance(data,dict):
            top=list(data.keys())[:20]
            rowkeys=[]
            for v in data.values():
                if isinstance(v,list) and v and isinstance(v[0],dict):
                    rowkeys=list(v[0].keys())[:30];break
                if isinstance(v,dict):
                    for vv in v.values():
                        if isinstance(vv,list) and vv and isinstance(vv[0],dict):
                            rowkeys=list(vv[0].keys())[:30];break
                    if rowkeys:break
            return f'top={top} row={rowkeys}'[:600]
        return f'type={type(data).__name__}'
    except Exception:
        return 'shape-unavailable'


def _parse_any(nh,data):
    """Parse daily rows without depending on exact response key casing."""
    out=[];seen=set()
    date_keys=('stck_bsop_date','bsop_date','bas_dt','trd_dd','trade_date','xymd','ymd','date')
    close_keys=('stck_clpr','clpr','close_prc','close','stck_prpr','prpr','last','trdprc')
    open_keys=('stck_oprc','oprc','open_prc','open')
    high_keys=('stck_hgpr','hgpr','high_prc','high')
    low_keys=('stck_lwpr','lwpr','low_prc','low')
    vol_keys=('acml_vol','acvol','tvol','volume','vol','trqu')

    for r in nh.walk(data):
        if not isinstance(r,dict):continue
        z={str(k).lower():v for k,v in r.items()}
        def first(keys):
            for k in keys:
                if k in z and z[k] not in (None,''):
                    return z[k]
            return None
        d=nh.normalize_date(first(date_keys))
        c=nh.num(first(close_keys))
        if not d or c<=0 or d in seen:continue
        seen.add(d)
        o=nh.num(first(open_keys)) or c
        h=nh.num(first(high_keys)) or c
        l=nh.num(first(low_keys)) or c
        v=nh.num(first(vol_keys))
        out.append({'date':d,'open':o,'high':h,'low':l,'close':c,'volume':v})
    out.sort(key=lambda x:x['date'])
    return out


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
                bars=nh.parse_daily_rows(data,'KR') or _parse_any(nh,data)
                if bars:
                    if code=='005930':
                        log_once(code,f'OK {market_cd} bars={len(bars)} last={bars[-1].get("date","")}')
                    return bars[-count:]
                errors.append(f'{market_cd}: {_meta(nh,data)} {_shape(data)}')
            except Exception as exc:
                errors.append(f'{market_cd}: {type(exc).__name__} {str(exc)[:180]}')

        log_once(code,' | '.join(errors)[-1000:] or 'no bars')
        return []

    feed._fetch_kr_daily=fetch_kr_daily
    print('NAMUH DATA PATCH: KR daily fetch/parser v2 active',flush=True)
