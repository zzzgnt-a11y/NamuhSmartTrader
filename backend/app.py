from __future__ import annotations
import os, time, logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from .nh_runtime import NhRuntime
from .strategy import scalp_score, smart_score
from .sector_engine import leading
from .aux_data import AuxMarketData
from .paper_state import protected_codes

load_dotenv()
logging.basicConfig(level=os.getenv("LOG_LEVEL","INFO"))
app=FastAPI(title="Namuh Smart Trader Live Data",version="0.4")
app.add_middleware(CORSMiddleware,allow_origins=["*"],allow_methods=["GET"],allow_headers=["*"])

nh=NhRuntime()
aux=AuxMarketData()

@app.on_event("startup")
def startup():
    nh.start()

@app.get("/api/health")
def health():
    return {
        "ok":True,
        "nh_realtime":nh.connected,
        "tracked":len(nh.codes),
        "scan_index":nh.scan_index,
        "scan_cycle_seconds":nh.scan_cycle_seconds,
        "last_error":nh.last_error[:300],
        "ts":time.time(),
        "orders_sent":0,
    }

@app.get("/api/market")
def market():
    data=aux.market()
    labels=["코스피","코스닥","코스피 야간선물","나스닥","필라델피아 반도체","나스닥 선물"]
    return {"items":[data.get(x,{"label":x,"value":None,"change_pct":None,"sparkline":[]}) for x in labels]}

@app.get("/api/sectors")
def sectors():
    return {"items":leading(nh.quotes)}

def _sector_scores():
    return {x["sector"]:x["score"] for x in leading(nh.quotes)}

def _candidate(q,smart=False):
    sec_scores=_sector_scores()
    ss=sec_scores.get(q.sector,0.0)
    score,reasons=(smart_score(q) if smart else scalp_score(q,ss,0.0))
    vi=q.open*1.10*(1-0.003) if q.open>0 else 0.0
    buy=getattr(q,"buy_volume",0.0); sell=getattr(q,"sell_volume",0.0)
    strength=(buy/max(sell,1))*100 if buy>0 or sell>0 else 100
    return {
        "code":q.code,"name":q.name or q.code,"price":q.price,"score":score,
        "execution_strength":strength,"sector_score":ss,"vi_pre":vi,
        "per":q.per,"pbr":q.pbr,"foreign_net":q.foreign_net,
        "institution_net":q.institution_net,"reasons":reasons,
        "price_series":list(q.prices)[-60:],
        "updated_at":q.updated_at,
    }

@app.get("/api/candidates/scalp")
def scalp():
    rows=[_candidate(q,False) for q in nh.quotes.values() if q.price>0]
    rows=[x for x in rows if x["price"] < (x["vi_pre"] or 1e99)]
    rows.sort(key=lambda x:x["score"],reverse=True)
    return {"items":rows[:30],"source":"NHPLUG KRX realtime","orders_sent":0}

@app.get("/api/candidates/smart")
def smart():
    rows=[_candidate(q,True) for q in nh.quotes.values() if q.price>0]
    rows.sort(key=lambda x:x["score"],reverse=True)
    return {"items":rows[:30],"source":"NHPLUG KRX realtime","orders_sent":0}

@app.get("/api/protected")
def protected():
    # 이 API는 실제 주문을 하지 않는다. 보호코드만 앱에 전달한다.
    # 실제 잔고 자동조회는 계좌/잔고 명세가 확정된 환경에서 연결하고,
    # 그 전에는 PROTECTED_CODES를 안전 기본값으로 사용한다.
    items=[]
    for c in sorted(protected_codes()):
        q=nh.quotes.get(c)
        items.append({"code":c,"name":q.name if q else c,"qty":0,"avg_price":0,"current_price":int(q.price) if q else 0})
    return {"items":items,"mode":"protected-only","orders_sent":0}

@app.get("/api/trades")
def trades():
    # 모의체결은 Android 로컬 PAPER 계좌에 기록된다.
    return {"items":[],"orders_sent":0}
