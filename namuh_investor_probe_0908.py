from __future__ import annotations

_INSTALLED=False

def apply(ns=None):
    global _INSTALLED
    if _INSTALLED:return True
    core=ns.get('core') if isinstance(ns,dict) else None
    if core is None:return False
    app=core.app;feed=core.feed
    if not any(getattr(r,'path','')=='/api/v364/investor-probe' for r in app.routes):
        @app.get('/api/v364/investor-probe')
        def investor_probe(code:str='000660'):
            from nhplug import call
            c=''.join(ch for ch in str(code) if ch.isdigit())[:6]
            if len(c)!=6:return {'ok':False,'error':'invalid code'}
            last='';data=None;market_used=''
            for market_cd in feed._market_order():
                try:
                    data=call('/krstock/quote/v1/currentInvestor',{'market_cd':market_cd,'iem_cd':c,'array_cnt':'14'})
                    market_used=market_cd;break
                except Exception as exc:last=str(exc)[:180]
            if data is None:return {'ok':False,'code':c,'error':last}
            keep_terms=('date','bsop','trd','frgn','foreign','prsn','person','orgn','gigwan','invest','program','prgm','pgtr','ntby','shnu','seln')
            rows=[]
            def walk(v):
                if isinstance(v,dict):
                    yield v
                    for x in v.values():yield from walk(x)
                elif isinstance(v,list):
                    for x in v:yield from walk(x)
            for o in walk(data):
                if not isinstance(o,dict):continue
                slim={str(k):v for k,v in o.items() if any(t in str(k).lower() for t in keep_terms)}
                if slim:rows.append(slim)
                if len(rows)>=20:break
            q=feed.quotes_for('KR').get(c)
            return {'ok':True,'code':c,'market_cd':market_used,'rows':rows,
                    'q':{'foreign':getattr(q,'foreign_net',None) if q else None,
                         'institution':getattr(q,'institution_net',None) if q else None,
                         'person':getattr(q,'person_net',None) if q else None,
                         'program':getattr(q,'program_net',None) if q else None,
                         'asof':getattr(q,'investor_asof','') if q else '',
                         'field_ready':getattr(q,'investor_field_ready',{}) if q else {}}}
    _INSTALLED=True
    print('NAMUH INVESTOR PROBE 0908 active',flush=True)
    return True
