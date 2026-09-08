from __future__ import annotations

import threading
import time


def apply(m):
    if getattr(m,'_NAMUH_UNIVERSE_PATCHED',False):return
    m._NAMUH_UNIVERSE_PATCHED=True
    lock=threading.RLock()
    all_scores={'KR':[],'US':[]}
    updated={'KR':0.0,'US':0.0}
    m._NAMUH_ALL_SCORES=all_scores
    m._NAMUH_ALL_SCORES_UPDATED=updated

    old_rebuild=m.rebuild_cache
    def rebuild_cache(market,now=None):
        scalp,smart=old_rebuild(market,now)
        market=m.normalize_market(market)
        if market in ('KR','US'):
            with lock:
                all_scores[market]=[dict(x) for x in scalp]
                updated[market]=time.time()
        return scalp,smart
    m.rebuild_cache=rebuild_cache

    def _cache_snapshot(market):
        try:
            with m.cache_lock:
                box=dict((m.CACHE.get(market) or {}))
                rows=[dict(x) for x in list(box.get('scalp') or []) if isinstance(x,dict)]
                stamp=float(box.get('updated_at') or 0.0)
            return rows,stamp
        except Exception:
            try:
                box=dict((m.CACHE.get(market) or {}))
                return [dict(x) for x in list(box.get('scalp') or []) if isinstance(x,dict)],float(box.get('updated_at') or 0.0)
            except Exception:
                return [],0.0

    def _live_map(market):
        with lock:
            rebuilt=[dict(x) for x in all_scores.get(market,[]) if isinstance(x,dict)]
            rebuilt_ts=float(updated.get(market,0.0) or 0.0)
        cached,cache_ts=_cache_snapshot(market)
        # The rendered CACHE is the final post-patch candidate set.  Older universe
        # wrappers can miss later rebuild_cache replacements and leave all_scores
        # empty/stale, which made the UI look as if only fixed names were detected.
        # Merge both sources by code, preferring the newest live CACHE row.
        merged={}
        for x in rebuilt:
            code=str(x.get('code') or '').upper().strip()
            if code:merged[code]=x
        for x in cached:
            code=str(x.get('code') or '').upper().strip()
            if code:merged[code]=x
        rows=list(merged.values())
        return rows,{str(x.get('code') or '').upper():x for x in rows},max(rebuilt_ts,cache_ts),bool(cached),len(rebuilt),len(cached)

    def _catalog(market,score_map):
        rows={}
        quotes=m.feed.quotes_for(market)
        if market=='KR':
            for code,meta in dict(getattr(m.feed,'kr_master_meta',{}) or {}).items():
                code=str(code or '').upper()
                if not code:continue
                meta=meta or {}
                q=quotes.get(code)
                s=score_map.get(code)
                rows[code]={
                    'market':'KR','code':code,
                    'name':str(meta.get('name') or getattr(q,'name','') or code),
                    'sector':str(meta.get('sector') or getattr(q,'sector','') or ''),
                    'price':float(getattr(q,'price',0) or 0),
                    'score':None if s is None else float(s.get('score',0) or 0),
                    'live':bool(q and getattr(q,'price',0)>0),
                }
        else:
            codes=list(dict.fromkeys(list(getattr(m.feed,'code_lists',{}).get('US',[]) or [])+
                                     list(getattr(m.feed,'fixed',{}).get('US',[]) or [])+
                                     list(quotes.keys())))
            for code in codes:
                code=str(code or '').upper()
                if not code:continue
                q=quotes.get(code);s=score_map.get(code)
                rows[code]={
                    'market':'US','code':code,'name':str(getattr(q,'name','') or code),
                    'sector':str(getattr(q,'sector','') or '미국주식'),
                    'price':float(getattr(q,'price',0) or 0),
                    'score':None if s is None else float(s.get('score',0) or 0),
                    'live':bool(q and getattr(q,'price',0)>0),
                }
        for code,s in score_map.items():
            if code not in rows:
                rows[code]={
                    'market':market,'code':code,'name':str(s.get('name') or code),
                    'sector':str(s.get('sector') or ''),
                    'price':float(s.get('price',0) or 0),'score':float(s.get('score',0) or 0),'live':True,
                }
        return sorted(rows.values(),key=lambda x:(not x.get('live'),str(x.get('name') or x.get('code'))))

    @m.app.get('/api/v352/universe')
    def v352_universe(market='KR',catalog:int=1):
        market=m.normalize_market(market)
        if market not in ('KR','US'):raise m.HTTPException(400,'stock market only')
        scores,score_map,stamp,has_cache,rebuilt_count,cache_count=_live_map(market)
        scores.sort(key=lambda x:(float(x.get('score',0) or 0),float(x.get('priority_score',0) or 0)),reverse=True)
        payload={
            'ok':True,'market':market,'scores':scores,
            'scored_count':len(scores),'updated_at':stamp,
            'entry_score':70,'entry_threshold':70,'model':'40/60','execution_weight':10,
            'score_source':'live_cache+rebuild' if has_cache else 'rebuild',
            'source_counts':{'cache':cache_count,'rebuild':rebuilt_count},
        }
        if int(catalog or 0):
            cat=_catalog(market,score_map)
            payload['catalog']=cat
            payload['catalog_count']=len(cat)
        return payload
