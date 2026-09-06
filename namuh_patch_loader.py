from __future__ import annotations
import importlib.abc, importlib.machinery, sys
_INSTALLED=False

def patch(m):
    if getattr(m,'_NAMUH_PATCH_BUNDLE',False):return
    m._NAMUH_PATCH_BUNDLE=True
    import namuh_vi_patch, namuh_score_patch, namuh_universe_patch
    namuh_vi_patch.apply(m)
    namuh_score_patch.apply(m)
    namuh_universe_patch.apply(m)
    old=m.health_payload
    def health():
        d=dict(old());rep={}
        try:
            row=m._minute_signal('999999',False);rep=(row or {}).get('recipe_report') or {}
        except Exception:pass
        d.update({
            'scalp_score_model':'40/60',
            'execution_weight':10,
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
