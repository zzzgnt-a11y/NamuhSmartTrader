from __future__ import annotations

import os
import re
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from engine import (
    PaperAccount, Quote, scalp_analysis, smart_analysis, smart_buy_eligibility,
    scalp_session, must_force_sell_pre
)
from nhfeed import NHFeed, aggregate_ticks
from events import DisclosureFeed

load_dotenv()
KST=timezone(timedelta(hours=9))
MARKETS=("KR","US")
feed=NHFeed()
paper=PaperAccount()
events=DisclosureFeed(lambda:feed.quotes_for("KR"))
protected={x.strip() for x in os.getenv("PROTECTED_CODES","").split(",") if x.strip()}
cache_lock=threading.Lock()
started=False

CACHE={
    "KR":{"sectors":[],"scalp":[],"smart":[],"stock_strength":{},"updated_at":0.0},
    "US":{"sectors":[],"scalp":[],"smart":[],"stock_strength":{},"updated_at":0.0},
}
SECTOR_FALLBACK={
    "005930":"반도체","000660":"반도체","042700":"반도체",
    "035420":"인터넷/AI","035720":"인터넷/AI","068270":"바이오",
    "012450":"방산","267260":"전력기기","005380":"자동차","000270":"자동차",
    "105560":"금융","055550":"금융","086790":"금융","028260":"지주","207940":"바이오",
}

def normalize_market(v):return "US" if str(v).upper()=="US" else "KR"
def krw(v):return int(round(float(v or 0)))

def trading_window(now:Optional[datetime]=None):
    now=(now.astimezone(KST) if now else datetime.now(KST));h=now.hour+now.minute/60
    if 8<=h<20 and now.weekday()<5:return "KR"
    if h>=20 and now.weekday()<5:return "US"
    if h<6 and (now-timedelta(days=1)).weekday()<5:return "US"
    return None

def default_view_market(now=None):return trading_window(now) or "KR"

def trading_day_key(market,now=None):
    now=(now.astimezone(KST) if now else datetime.now(KST))
    if market=="US" and now.hour<6:now-=timedelta(days=1)
    return now.strftime("%Y-%m-%d")

def smart_buy_window(now=None):
    now=(now or datetime.now(KST)).astimezone(KST);m=now.hour*60+now.minute
    return now.weekday()<5 and 540<=m<920

# High-impact macro calendar. Dates are sourced from the official Federal
# Reserve and U.S. Bureau of Labor Statistics release schedules. The API
# converts the official U.S. Eastern release time to KST so the dashboard
# calendar is useful without the user doing timezone math.
_FOMC_2026=[
    ("2026-01-28","Jan 27-28",False),("2026-03-18","Mar 17-18",True),
    ("2026-04-29","Apr 28-29",False),("2026-06-17","Jun 16-17",True),
    ("2026-07-29","Jul 28-29",False),("2026-09-16","Sep 15-16",True),
    ("2026-10-28","Oct 27-28",False),("2026-12-09","Dec 8-9",True),
]
_FOMC_2027=[
    ("2027-01-27","Jan 26-27",False),("2027-03-17","Mar 16-17",True),
    ("2027-04-28","Apr 27-28",False),("2027-06-09","Jun 8-9",True),
    ("2027-07-28","Jul 27-28",False),("2027-09-15","Sep 14-15",True),
    ("2027-10-27","Oct 26-27",False),("2027-12-08","Dec 7-8",True),
]
_CPI_2026=["2026-01-13","2026-02-13","2026-03-11","2026-04-10","2026-05-12","2026-06-10","2026-07-14","2026-08-12","2026-09-11","2026-10-14","2026-11-10","2026-12-10"]
_PPI_2026=["2026-01-14","2026-01-30","2026-02-27","2026-03-18","2026-04-14","2026-05-13","2026-06-11","2026-07-15","2026-08-13","2026-09-10","2026-10-15","2026-11-13","2026-12-15"]
_NFP_2026=["2026-01-09","2026-02-11","2026-03-06","2026-04-03","2026-05-08","2026-06-05","2026-07-02","2026-08-07","2026-09-04","2026-10-02","2026-11-06","2026-12-04"]

def _macro_event(us_date,et_time,label,title,source,url,importance="high",note=""):
    et=ZoneInfo("America/New_York")
    dt=datetime.strptime(f"{us_date} {et_time}","%Y-%m-%d %H:%M").replace(tzinfo=et).astimezone(KST)
    return {
        "date":dt.strftime("%Y-%m-%d"),"time_kst":dt.strftime("%H:%M"),
        "official_date":us_date,"official_time_et":et_time,"label":label,"title":title,
        "importance":importance,"source":source,"url":url,"note":note,
    }

def macro_calendar_payload():
    out=[]
    fed_url="https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
    bls_url="https://www.bls.gov/schedule/"
    for us_date,meeting,sep in _FOMC_2026+_FOMC_2027:
        title="FOMC 금리결정 · 기자회견"+(" · SEP" if sep else "")
        out.append(_macro_event(us_date,"14:00","FOMC",title,"Federal Reserve",fed_url,"critical",f"미국 현지 회의 {meeting}"))
    for d in _CPI_2026:
        out.append(_macro_event(d,"08:30","CPI","미국 소비자물가지수(CPI)","U.S. BLS",bls_url,"critical"))
    for d in _PPI_2026:
        out.append(_macro_event(d,"08:30","PPI","미국 생산자물가지수(PPI)","U.S. BLS",bls_url,"high"))
    for d in _NFP_2026:
        out.append(_macro_event(d,"08:30","NFP","미국 고용보고서(Employment Situation)","U.S. BLS",bls_url,"critical"))
    out.sort(key=lambda x:(x["date"],x["time_kst"],x["label"]))
    return out

def schedule_payload(now=None):
    now=(now.astimezone(KST) if now else datetime.now(KST));active=trading_window(now);ss=scalp_session(now)
    return {
        "kst":now.isoformat(),"active_market":active,"default_view":default_view_market(now),
        "kr_hours":"08:00~20:00 KST","us_hours":"20:00~06:00 KST",
        "kr_scalp_session":ss,
        "kr_scalp_rules":"08:00 시작 · 08:49 이전 전량청산 / 09:00 시작 / 14:30 후반세션",
        "trading_enabled":active is not None,
        "label":"국장 자동매매 시간" if active=="KR" else "미장 자동매매 시간" if active=="US" else "자동매매 대기시간",
    }

def sector_name(q,market):
    return q.sector or (SECTOR_FALLBACK.get(q.code,"기타") if market=="KR" else "미국주식")

def _vol_ratio(q):
    return (q.volume/q.prev_day_volume*100) if q.prev_day_volume>0 else 0.0

def build_sector_context(market):
    groups={}
    for q in list(feed.quotes_for(market).values()):
        if q.price<=0 or q.open<=0:continue
        sec=sector_name(q,market);g=groups.setdefault(sec,[])
        g.append(q)
    sectors=[];stock_strength={}
    for sec,qs in groups.items():
        changes=[(q.price/q.open-1)*100 for q in qs if q.open>0]
        avg=sum(changes)/len(changes) if changes else 0
        breadth=sum(x>0 for x in changes)/len(changes)*100 if changes else 0
        vols=[_vol_ratio(q) for q in qs if _vol_ratio(q)>0]
        avg_vol=sum(vols)/len(vols) if vols else 0
        f=sum(q.foreign_net for q in qs) if market=="KR" else 0
        i=sum(q.institution_net for q in qs) if market=="KR" else 0
        p=sum(q.program_net for q in qs) if market=="KR" else 0
        money=sum(q.price*q.volume for q in qs)
        leader=max(qs,key=lambda q:(q.price/q.open-1) if q.open else -999)
        if market=="KR":
            # Flow-heavy sector score: direction + breadth + volume + price momentum.
            flow=(1.5 if f>0 else 0)+(1.5 if i>0 else 0)+(1.0 if p>0 else 0)
            score=flow
            score+=min(2,max(0,(breadth-40)/30))
            score+=min(2,max(0,(avg_vol-30)/70*2))
            score+=min(2,max(0,(avg+0.5)*1.2))
        else:
            score=min(10,max(0,(avg+1)*2.2)+(1 if money>0 else 0))
        score=round(max(0,min(10,score)),1)
        sectors.append({"sector":sec,"change_pct":avg,"leader":leader.name or leader.code,"score":score,
                        "foreign_net":f if market=="KR" else None,
                        "institution_net":i if market=="KR" else None,
                        "program_net":p if market=="KR" else None,
                        "volume_ratio":avg_vol,"breadth":breadth})
        # Strong stocks inside a strong sector: relative volume + actual three-way flow direction.
        sorted_vol=sorted(qs,key=_vol_ratio)
        for q in qs:
            vrank=(sorted_vol.index(q)+1)/len(sorted_vol) if sorted_vol else 0
            if market=="KR":
                dirs=sum(x>0 for x in (q.foreign_net,q.institution_net,q.program_net))/3
                s=2.5*vrank+2.5*dirs
            else:
                s=2.5*vrank
            stock_strength[q.code]=round(max(0,min(5,s)),1)
    sectors.sort(key=lambda x:x["score"],reverse=True)
    return sectors[:12],{x["sector"]:x["score"] for x in sectors},stock_strength

def candidate(q,market,smart=False,secmap=None,stockmap=None,now=None):
    sec=sector_name(q,market)
    if smart:
        a=smart_analysis(q)
        eligible,rank,elig_reason=smart_buy_eligibility(q,now)
    else:
        a=scalp_analysis(q,(secmap or {}).get(sec,0),(stockmap or {}).get(q.code,0),market,now)
        eligible=rank=None;elig_reason=""
    vi_pre=q.open*1.10*0.997 if market=="KR" and q.open else None
    return {
        "market":market,"code":q.code,"name":q.name or q.code,"sector":sec,
        "currency":"KRW" if market=="KR" else "USD",
        "price":krw(q.price) if market=="KR" else round(float(q.price),4),
        "open":krw(q.open) if market=="KR" else round(float(q.open),4),
        "score":a["score"],"score_breakdown":a.get("breakdown",{}),"phase":a.get("phase",""),
        "execution_strength":q.execution_strength,
        "per":q.per if smart else None,"pbr":q.pbr if smart else None,
        "foreign_net":q.foreign_net if market=="KR" else None,
        "institution_net":q.institution_net if market=="KR" else None,
        "program_net":q.program_net if market=="KR" else None,
        "volume_ratio":round(_vol_ratio(q),1) if q.prev_day_volume>0 else None,
        "vi_pre":krw(vi_pre) if vi_pre else None,
        "reasons":a["reasons"],
        "series":[krw(x) if market=="KR" else round(float(x),4) for x in list(q.prices)[-24:]],
        "smart_buy_eligible":eligible if smart else None,
        "smart_close_rank":rank if smart else None,
        "smart_eligibility_reason":elig_reason if smart else None,
        "event":q.events[0] if q.events else None,
    }

def rebuild_cache(market,now=None):
    market=normalize_market(market)
    sectors,secmap,stockmap=build_sector_context(market)
    quotes=[q for q in feed.quotes_for(market).values() if q.price>0]
    scalp=[];smart=[]
    for q in quotes:
        try:
            scalp.append(candidate(q,market,False,secmap,stockmap,now))
            if market=="KR":smart.append(candidate(q,market,True,now=now))
        except Exception:
            continue
    scalp.sort(key=lambda x:x["score"],reverse=True);smart.sort(key=lambda x:x["score"],reverse=True)
    with cache_lock:
        CACHE[market]={"sectors":sectors,"scalp":scalp[:50],"smart":smart[:50] if market=="KR" else [],
                       "stock_strength":stockmap,"updated_at":time.time()}
    return scalp,smart

def _fx(market):return feed.usdkrw if market=="US" else 1.0

def mark_and_sell(market,scalp_candidates,smart_candidates,now=None):
    now=(now or datetime.now(KST)).astimezone(KST);fx=_fx(market)
    if market=="US" and fx<=0:return
    quotes=feed.quotes_for(market)
    scalp_map={x["code"]:x["score"] for x in scalp_candidates}
    smart_map={x["code"]:x["score"] for x in smart_candidates}
    for p in list(paper.market_positions(market)):
        q=quotes.get(p.code)
        if not q or q.price<=0:continue
        paper.mark(market,p.code,q.price,fx)
        score=(smart_map if p.strategy=="SMART" else scalp_map).get(p.code,50)
        reason=""
        if market=="KR" and must_force_sell_pre(p,now):reason="08:49 프리세션 강제청산"
        elif p.pnl_pct>=2.5:reason="목표수익 도달"
        elif p.pnl_pct<=-1.5:reason="손절 기준 도달"
        elif score<46:reason="AI 점수 이탈"
        if reason:paper.sell(market,p.code,q.price,fx,reason)

def _buy_one(market,item,strategy,entry_session,now=None):
    q=feed.quotes_for(market).get(item["code"])
    if not q or q.price<=0:return False
    fx=_fx(market)
    if market=="US" and fx<=0:return False
    day=trading_day_key(market,now);budget=paper.effective_budget_krw(day)
    unit=q.price*(fx if market=="US" else 1.0)
    remain=min(paper.cash_krw,budget-paper.held_cost_krw())
    if remain<unit:return False
    target=min(remain,max(unit,budget/2));qty=int(target//unit)
    if qty<1:return False
    return paper.buy(q,qty,market,fx,day,strategy=strategy,entry_session=entry_session) is not None

def trade_scalp(market,candidates,now=None):
    now=(now or datetime.now(KST)).astimezone(KST)
    if market=="KR":
        session=scalp_session(now)
        if session not in ("PRE08","REGULAR","LATE"):return
    else:
        session="US"
    for item in candidates:
        if len(paper.market_positions(market))>=3 or item["score"]<72:break
        code=item["code"]
        if market=="KR" and code in protected:continue
        if f"{market}:{code}" in paper.positions:continue
        if market=="KR" and item.get("vi_pre") and item["price"]>=item["vi_pre"]:continue
        if _buy_one(market,item,"SCALP",session,now):break

def trade_smart_kr(candidates,now=None):
    now=(now or datetime.now(KST)).astimezone(KST)
    if not smart_buy_window(now):return
    for item in candidates:
        if len(paper.market_positions("KR"))>=3 or item["score"]<72:break
        if not item.get("smart_buy_eligible"):continue
        code=item["code"]
        if code in protected or f"KR:{code}" in paper.positions:continue
        if _buy_one("KR",item,"SMART","NEXT_DAY_CLOSE_SIGNAL",now):break

def ai_loop():
    while True:
        try:
            now=datetime.now(KST)
            kr_scalp,kr_smart=rebuild_cache("KR",now)
            us_scalp,_=rebuild_cache("US",now)
            active=trading_window(now)
            if active=="KR":
                mark_and_sell("KR",kr_scalp,kr_smart,now)
                trade_scalp("KR",kr_scalp,now)
                trade_smart_kr(kr_smart,now)
            elif active=="US":
                mark_and_sell("US",us_scalp,[],now)
                trade_scalp("US",us_scalp,now)
        except Exception as exc:
            print("AI LOOP ERROR:",exc,flush=True)
        time.sleep(5)

def nh_feed_bootstrap():
    from nhplug.auth import get_token
    delay=2
    while True:
        try:
            get_token();print("NH AUTH READY - starting market feeds",flush=True)
            feed.start();return
        except Exception as exc:
            print("NH AUTH WAIT:",str(exc),flush=True);time.sleep(delay);delay=min(delay*2,60)

def start_background():
    global started
    if started:return
    started=True
    if os.getenv("NHPLUG_APP_KEY") and os.getenv("NHPLUG_APP_SECRET"):
        threading.Thread(target=nh_feed_bootstrap,daemon=True).start()
    threading.Thread(target=ai_loop,daemon=True).start()
    events.start()

@asynccontextmanager
async def lifespan(_app):
    start_background();yield

app=FastAPI(title="GY 모의투자 시스템",lifespan=lifespan)
app.mount("/static",StaticFiles(directory="static"),name="static")

@app.get("/")
def home():
    return FileResponse("static/index.html",headers={"Cache-Control":"no-store, max-age=0"})

INDEX_KEYS={
    "KR":{"kospi","kosdaq","kospi_night","nasdaq_future","sox"},
    "US":{"sp500","nasdaq","nasdaq_future","sox"},
}

@app.get("/index/{market}/{key}")
def index_page(market:str,key:str):
    market=normalize_market(market);key=str(key).lower()
    if key not in INDEX_KEYS[market]:raise HTTPException(404,"index not available in this market mode")
    return FileResponse("static/index-detail.html",headers={"Cache-Control":"no-store, max-age=0"})

@app.get("/stock/{market}/{code}")
def stock_page(market:str,code:str):
    market=normalize_market(market)
    if market=="KR" and not re.fullmatch(r"\d{6}",code):raise HTTPException(404)
    if market=="US" and not re.fullmatch(r"[A-Za-z0-9.\-]{1,12}",code):raise HTTPException(404)
    return FileResponse("static/stock.html",headers={"Cache-Control":"no-store, max-age=0"})

def health_payload():
    h=feed.health()
    return {"ok":True,"nh_configured":bool(os.getenv("NHPLUG_APP_KEY") and os.getenv("NHPLUG_APP_SECRET")),
            "nh_realtime":h["nh_realtime"],"realtime":h["realtime"],"errors":h["errors"],"orders_sent":0,
            "kr_tracked":h["kr_tracked"],"kr_priced":h["kr_priced"],"us_tracked":h["us_tracked"],"us_priced":h["us_priced"],
            "market_updated_at":h["market_updated_at"],"market_errors":h["market_errors"],"usdkrw":h["usdkrw"],
            "usdkrw_asof":h["usdkrw_asof"],"program_realtime":h.get("program_realtime",{}),
            "investor_updated_at":h.get("investor_updated_at",0),"history_updated_at":h.get("history_updated_at",0),
            "future_symbols":h.get("future_symbols",{}),"schedule":schedule_payload()}

@app.get("/api/health")
def health():return health_payload()

class BudgetRequest(BaseModel):
    amount:Optional[int]=None
    auto_max_if_unset:bool=True

@app.post("/api/budget")
def set_budget(data:BudgetRequest):
    active=trading_window() or default_view_market();day=trading_day_key(active)
    paper.set_auto_max(data.auto_max_if_unset);paper.set_budget(data.amount,day)
    return {"ok":True,"budget_day":paper.budget_day,"explicit_budget":paper.explicit_budget_krw,
            "auto_max_if_unset":paper.auto_max_if_unset,"effective_budget":paper.effective_budget_krw(day),
            "initial_cash":paper.initial_cash_krw}

def paper_state(market):
    active=trading_window() or default_view_market();day=trading_day_key(active)
    pos=[]
    for p in paper.market_positions(market):
        pos.append({"market":p.market,"code":p.code,"name":p.name,"qty":p.qty,"avg_price":p.avg_price,
                    "current_price":p.current_price,"currency":"USD" if p.market=="US" else "KRW",
                    "fx_buy":p.fx_buy if p.market=="US" else None,"fx_current":p.fx_current if p.market=="US" else None,
                    "cost_krw":krw(p.cost_krw),"value_krw":krw(p.value_krw),"pnl":krw(p.pnl_krw),"pnl_pct":p.pnl_pct,
                    "strategy":p.strategy,"entry_session":p.entry_session})
    trades=[t for t in paper.trades if t.get("market")==market][:100]
    return {"initial_cash":paper.initial_cash_krw,"cash":krw(paper.cash_krw),"equity":krw(paper.equity_krw()),
            "budget_day":paper.budget_day,"explicit_budget":paper.explicit_budget_krw,
            "budget":paper.effective_budget_krw(day),"effective_budget":paper.effective_budget_krw(day),
            "auto_max_if_unset":paper.auto_max_if_unset,"held_cost":krw(paper.held_cost_krw()),
            "market_held_cost":krw(paper.held_cost_krw(market)),"positions":pos,"trades":trades,
            "auto_trade_enabled":trading_window()==market,"usdkrw":feed.usdkrw,"usdkrw_asof":feed.usdkrw_asof}

def market_separation_check(market,scalp,smart,positions):
    codes=[str(x.get("code","")) for x in scalp+smart+positions]
    bad=[c for c in codes if (re.fullmatch(r"\d{6}",c) if market=="US" else (c and not re.fullmatch(r"\d{6}",c)))]
    return {"ok":not bad,"market":market,"bad_codes":sorted(set(bad))}

@app.get("/api/state")
def state(market:str=Query("KR")):
    market=normalize_market(market)
    scan_active=trading_window()==market
    with cache_lock:
        c=CACHE[market];sectors=list(c["sectors"]);updated=c["updated_at"]
        # Keep the analysis cache warm in the background, but do not fill the
        # closed-market dashboard with zero/stale candidate cards.
        scalp=list(c["scalp"][:30]) if scan_active else []
        smart=(list(c["smart"][:30]) if market=="KR" and scan_active else [])
    ps=paper_state(market);sep=market_separation_check(market,scalp,smart,ps["positions"])
    return {"mode":market,"health":health_payload(),"schedule":schedule_payload(),"market":feed.market_state(market),
            "session":feed.session_state(market),"sectors":sectors,"scalp":scalp,"smart":smart,
            "candidate_scan_active":scan_active,"macro_events":macro_calendar_payload(),
            "events":events.state(market),"cache_updated_at":updated,"paper":ps,
            "protected_codes":sorted(protected) if market=="KR" else [],"market_separation":sep}

def _analysis_for_bars(q,market,bars):
    if len(bars)<20:return None
    temp=Quote(q.code,q.name,q.sector)
    temp.price=q.price;temp.open=q.open;temp.high=q.high;temp.low=q.low;temp.volume=q.volume;temp.prev_day_volume=q.prev_day_volume
    temp.foreign_net=q.foreign_net;temp.institution_net=q.institution_net;temp.program_net=q.program_net
    temp.execution_strength=q.execution_strength;temp.execution_history=q.execution_history.copy();temp.flow_history=q.flow_history.copy()
    temp.daily_bars=q.daily_bars.copy();temp.events=q.events;temp.event_score=q.event_score;temp.event_blocked=q.event_blocked
    for b in bars[-60:]:temp.prices.append(float(b["close"]))
    # Detail score is descriptive; use current sector context and same live gate.
    with cache_lock:
        secmap={x["sector"]:x["score"] for x in CACHE[market]["sectors"]}
        stockmap=CACHE[market]["stock_strength"]
    return scalp_analysis(temp,secmap.get(sector_name(q,market),0),stockmap.get(q.code,0),market)

@app.get("/api/stock/{market}/{code}")
def stock_detail(market:str,code:str,timeframe:str=Query("1d")):
    market=normalize_market(market);code=code.upper()
    q=feed.quotes_for(market).get(code)
    if not q:raise HTTPException(404,"tracked stock not found")
    # Detail pages must not wait for the background history loop. Pull the
    # latest 30 official daily bars on demand when they are not warm yet.
    try:feed.ensure_daily_bars(market,code,30)
    except Exception:pass
    bars=feed.bars(market,code,timeframe)
    analysis=_analysis_for_bars(q,market,bars)
    scores={}
    for tf in ("1m","3m","5m","20m","1d"):
        tb=feed.bars(market,code,tf);a=_analysis_for_bars(q,market,tb)
        scores[tf]=a["score"] if a else None
    return {
        "market":market,"code":code,"name":q.name or code,"sector":sector_name(q,market),
        "price":q.price,"currency":"KRW" if market=="KR" else "USD","timeframe":timeframe,
        "bars":bars,"scores":scores,"analysis":analysis,
        "flow":{"foreign_net":q.foreign_net if market=="KR" else None,
                "institution_net":q.institution_net if market=="KR" else None,
                "program_net":q.program_net if market=="KR" else None,
                "execution_strength":q.execution_strength if market=="KR" else None,
                "volume_ratio":round(_vol_ratio(q),1) if q.prev_day_volume>0 else None},
        "events":q.events if market=="KR" else [],
        "daily_bars":list(q.daily_bars)[-30:],
    }

@app.get("/api/index/{market}/{key}")
def index_detail(market:str,key:str,timeframe:str=Query("1d")):
    market=normalize_market(market);key=str(key).lower();tf=str(timeframe).lower()
    if key not in INDEX_KEYS[market]:raise HTTPException(404,"index not available in this market mode")
    if tf not in ("1m","3m","1d"):raise HTTPException(400,"timeframe must be 1m, 3m or 1d")
    item=feed.market_item(key)
    if not item:raise HTTPException(404,"index data not ready")
    bars=feed.market_bars(key,tf)
    return {
        "market":market,"key":key,"label":item.get("label",key),"value":item.get("value"),
        "change":item.get("change"),"change_pct":item.get("change_pct"),"status":item.get("status",""),
        "source":item.get("source",""),"asof":item.get("asof",""),"timeframe":tf,"bars":bars,
        "market_open":feed.market_open_for_key(key),
        "note":"1·3분봉은 서버가 공식 시세를 수신한 시점부터 집계됩니다." if tf in ("1m","3m") else "공식 일별 OHLC 데이터",
    }

@app.get("/api/market-check")
def market_check():
    out={}
    for market in MARKETS:
        with cache_lock:
            c=CACHE[market];scalp=list(c["scalp"][:30]);smart=list(c["smart"][:30]) if market=="KR" else []
        out[market]=market_separation_check(market,scalp,smart,paper_state(market)["positions"])
    kr_labels=[x["label"] for x in feed.market_state("KR")];us_labels=[x["label"] for x in feed.market_state("US")]
    checks={
        "market_separation":out["KR"]["ok"] and out["US"]["ok"],
        "kr_index_order":kr_labels==["코스피","코스닥","코스피 야간선물","나스닥 선물","필라델피아 반도체지수"],
        "us_index_order":us_labels==["S&P500","나스닥","나스닥 선물","필라델피아 반도체지수"],
        "nxt_not_index":"NXT" not in kr_labels and "NXT" not in us_labels,
        "orders_sent_zero":health_payload()["orders_sent"]==0,
        "us_smart_disabled":CACHE["US"]["smart"]==[],
    }
    return {"ok":all(checks.values()),"checks":checks,"markets":out,"orders_sent":0}

if __name__=="__main__":
    import uvicorn
    uvicorn.run("app:app",host=os.getenv("HOST","0.0.0.0"),port=int(os.getenv("PORT","8787")),reload=False)
