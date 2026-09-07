from __future__ import annotations
import importlib.abc, importlib.machinery, sys
_INSTALLED=False

def patch(m):
    if getattr(m,'_NAMUH_PATCH_BUNDLE',False):return
    m._NAMUH_PATCH_BUNDLE=True
    import namuh_vi_patch, namuh_score_patch, namuh_kr_score_display_patch, namuh_score_503020_patch, namuh_daily_fetch_patch, namuh_universe_patch
    namuh_vi_patch.apply(m)
    namuh_score_patch.apply(m)
    namuh_kr_score_display_patch.apply(m)
    namuh_score_503020_patch.apply(m)
    namuh_daily_fetch_patch.apply(m)
    namuh_universe_patch.apply(m)

    # KR intraday fail-soft: an upstream daily-history outage must not stop all trading.
    # Missing daily data contributes 0/15 points, but only the daily gate is skipped.
    # Execution strength, orderbook, 1m, technical confirmation, event block and the
    # final score threshold remain active. As soon as daily_score is present again,
    # the normal >=25 daily gate is used automatically.
    old_candidate=m.candidate
    def candidate_failsoft(*args,**kwargs):
        out=old_candidate(*args,**kwargs)
        if not isinstance(out,dict):return out
        market=str(args[1] if len(args)>1 else kwargs.get('market','')).upper()
        if market!='KR' or out.get('daily_score') is not None:
            return out
        q=args[0] if args else kwargs.get('q')
        blocked=bool(getattr(q,'event_blocked',False)) if q is not None else False
        try:
            blocked=blocked or any(bool(x.get('blocked')) for x in list(getattr(q,'events',[]) or []) if isinstance(x,dict))
        except Exception:pass
        out['daily_gate_pass']=True
        out['daily_failsoft']=True
        out['entry_gate_pass']=bool(
            out.get('execution_gate_pass',False)
            and out.get('orderbook_gate_pass',False)
            and out.get('minute_gate_pass',False)
            and out.get('technical_gate_pass',False)
            and not blocked
        )
        reasons=[]
        for r in list(out.get('reasons') or []):
            if str(r).startswith('일봉 데이터 대기'):
                reasons.append('일봉 API 장애 · 0/15 · Gate만 임시 통과')
            else:
                reasons.append(r)
        out['reasons']=reasons
        return out
    m.candidate=candidate_failsoft

    old=m.health_payload
    def health():
        d=dict(old());rep={}
        try:
            row=m._minute_signal('999999',False);rep=(row or {}).get('recipe_report') or {}
        except Exception:pass
        d.update({
            'scalp_score_model':'50/30/20',
            'execution_weight':15,
            'kr_daily_failsoft':True,
            'execution_calibration':((rep.get('execution_strength') or {}).get('status') if isinstance(rep,dict) else None) or 'PENDING',
            'vi_reentry_watch':len(getattr(m,'_NAMUH_VI_STATE',{})),
            'all_ai_scored':{k:len(v) for k,v in getattr(m,'_NAMUH_ALL_SCORES',{}).items()},
        })
        return d
    m.health_payload=health

class Loader(importlib.abc.Loader):
    def __init__(self,w):self.w=w
    def create_module(self,s):return self.w.create_module(s) if hasattr(self.w,'create_module') else None
    def exec_module(self,m):self.w.exec_module(m);patch(m)
class Finder(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,path,target=None):
        if fullname!='app':return None
        s=importlib.machinery.PathFinder.find_spec(fullname,path)
        if s and s.loader and not isinstance(s.loader,Loader):s.loader=Loader(s.loader)
        return s

def install():
    global _INSTALLED
    if _INSTALLED:return
    _INSTALLED=True
    if 'app' in sys.modules:
        try:patch(sys.modules['app'])
        except Exception:pass
    else:sys.meta_path.insert(0,Finder())
