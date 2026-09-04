from __future__ import annotations
import os, time, requests
from typing import Dict, List

YF = {
    "코스피":"^KS11",
    "코스닥":"^KQ11",
    "나스닥":"^IXIC",
    "필라델피아 반도체":"^SOX",
    "나스닥 선물":"NQ=F",
}

class AuxMarketData:
    """
    AI의 국내주식 매수/매도 신호에는 사용하지 않는 대시보드 보조원.
    Yahoo chart 응답은 거래소/상품별 지연 가능성이 있어 source에 표시한다.
    KOSPI 야간선물은 NH 파생 실시간 코드 연결이 필요한 별도 항목이다.
    """
    def __init__(self):
        self.cache={}
        self.ts=0

    def _yf(self, symbol):
        url=f"https://query1.finance.yahoo.com/v8/finance/chart/{requests.utils.quote(symbol,safe='')}?interval=1m&range=1d"
        r=requests.get(url,timeout=3,headers={"User-Agent":"Mozilla/5.0"})
        r.raise_for_status()
        obj=r.json()["chart"]["result"][0]
        meta=obj.get("meta",{})
        vals=[x for x in obj.get("indicators",{}).get("quote",[{}])[0].get("close",[]) if x is not None]
        cur=meta.get("regularMarketPrice") or (vals[-1] if vals else None)
        prev=meta.get("chartPreviousClose") or meta.get("previousClose")
        pct=((cur/prev)-1)*100 if cur and prev else None
        return cur,pct,vals[-30:]

    def market(self):
        now=time.time()
        if now-self.ts<20 and self.cache: return self.cache
        out={}
        if os.getenv("ENABLE_MARKET_DASHBOARD_FALLBACK","1")!="1":
            return out
        for label,sym in YF.items():
            try:
                v,p,s=self._yf(sym); out[label]={"label":label,"value":v,"change_pct":p,"sparkline":s,"source":"Yahoo chart (지연 가능)"}
            except Exception:
                pass
        out["코스피 야간선물"]={"label":"코스피 야간선물","value":None,"change_pct":None,"sparkline":[],"source":"NH 파생 실시간 코드 연결 필요"}
        self.cache=out; self.ts=now
        return out
