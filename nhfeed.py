from __future__ import annotations
import os,time,threading,re,logging
from typing import Dict,Any
from engine import Quote
log=logging.getLogger("nhfeed")

def walk(o):
    if isinstance(o,dict):
        yield o
        for v in o.values(): yield from walk(v)
    elif isinstance(o,list):
        for v in o: yield from walk(v)

def num(v):
    try:return float(str(v).replace(",","").replace("+",""))
    except:return 0

def pick(data,keys):
    for d in walk(data):
        for k in keys:
            if k in d and d[k] not in (None,""): 
                x=num(d[k])
                if x: return x
    return 0

def code_of(data):
    for d in walk(data):
        for k in ("iem_cd","stck_shrn_iscd","code","symbol","tr_key"):
            v=str(d.get(k,""))
            m=re.search(r"\b(\d{6})\b",v)
            if m:return m.group(1)
    return ""

class NHFeed:
    def __init__(self):
        self.quotes:Dict[str,Quote]={}
        self.connected=False
        self.error=""
        self.fixed=[x.strip() for x in os.getenv("TRACKED_CODES","").split(",") if x.strip()]
        self.all_codes=[]
        self.scan_index=0
    def q(self,c):
        if c not in self.quotes:self.quotes[c]=Quote(c,c)
        return self.quotes[c]
    def _apply(self,c,data):
        q=self.q(c)
        p=pick(data,("stck_prpr","price","prc","cur_pr","now_pr","last_price"))
        v=pick(data,("acml_vol","volume","vol"))
        if p:q.mark(p,v)
        q.open=pick(data,("stck_oprc","open")) or q.open
        q.high=pick(data,("stck_hgpr","high")) or q.high
        q.low=pick(data,("stck_lwpr","low")) or q.low
        q.per=pick(data,("per","per_val")) or q.per
        q.pbr=pick(data,("pbr","pbr_val")) or q.pbr
        q.foreign_net=pick(data,("frgn_ntby_qty","foreign_net")) or q.foreign_net
        q.institution_net=pick(data,("orgn_ntby_qty","institution_net")) or q.institution_net
    def load_master(self):
        try:
            from nhplug.instruments import load_master
            df=load_master("m_new_stock")
            cols=list(map(str,df.columns))
            cc=next((c for c in cols if "code" in c.lower() or "단축" in c or "종목코드" in c),None)
            nc=next((c for c in cols if "name" in c.lower() or "종목명" in c or "한글" in c),None)
            sc=next((c for c in cols if "업종" in c or "sector" in c.lower() or "industry" in c.lower()),None)
            arr=[]
            if cc:
                for _,r in df.iterrows():
                    m=re.search(r"(\d{6})",str(r.get(cc,"")))
                    if not m:continue
                    c=m.group(1); q=self.q(c)
                    if nc:q.name=str(r.get(nc,"") or c)
                    if sc:q.sector=str(r.get(sc,"") or "")
                    arr.append(c)
            self.all_codes=list(dict.fromkeys(arr))
        except Exception as e:
            self.error=f"master: {e}"; self.all_codes=self.fixed[:]
    def scanner(self):
        self.load_master()
        codes=self.all_codes or self.fixed
        if not codes:return
        from nhplug import call
        while True:
            c=codes[self.scan_index%len(codes)]
            self.scan_index=(self.scan_index+1)%len(codes)
            try:
                data=call("/krstock/quote/v1/currentPrice",{"iem_cd":c,"market_cd":"KRX"})
                self._apply(c,data)
            except Exception as e:
                self.error=str(e)[:300]
                if "429" in self.error:time.sleep(1)
            time.sleep(.28)
    def priority(self):
        rows=[]
        for c,q in self.quotes.items():
            if q.price<=0:continue
            chg=abs((q.price/q.open-1)*100) if q.open else 0
            rows.append((chg,c))
        rows.sort(reverse=True)
        out=[c for _,c in rows[:10]]
        for c in self.fixed:
            if c not in out:out.append(c)
            if len(out)>=10:break
        return out[:10]
    def on_tick(self,msg):
        c=code_of(msg)
        if not c:return
        self._apply(c,msg); self.connected=True
    def websocket(self):
        from nhplug.realtime import subscribe
        while True:
            keys=self.priority() or self.fixed[:10]
            if not keys:
                time.sleep(2);continue
            try:subscribe(keys,self.on_tick,max_messages=200)
            except Exception as e:
                self.connected=False; self.error=str(e)[:300]; time.sleep(2)
    def start(self):
        threading.Thread(target=self.scanner,daemon=True).start()
        threading.Thread(target=self.websocket,daemon=True).start()
