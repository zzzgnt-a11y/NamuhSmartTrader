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
    PaperAccount, Position, Quote, scalp_analysis, smart_analysis, smart_buy_eligibility,
    scalp_session, must_force_sell_pre
)
from nhfeed import NHFeed, aggregate_ticks
from events import DisclosureFeed
from state_store import StateStore
from coinone_feed import CoinoneFeed, CryptoPaperAccount

load_dotenv()
KST=timezone(timedelta(hours=9))
MARKETS=("KR","US")
SUPPORTED_MODES=("KR","US","COIN")
feed=NHFeed()
paper=PaperAccount()
coin_feed=CoinoneFeed(top_n=int(os.getenv("COIN_SCAN_TOP_N","40") or 40))
coin_paper=CryptoPaperAccount(initial_cash_krw=int(os.getenv("COIN_PAPER_INITIAL_CASH","1500000") or 1500000))
store=StateStore()
events=DisclosureFeed(lambda:feed.quotes_for("KR"))
BUILD_ID=(os.getenv("RENDER_GIT_COMMIT") or os.getenv("GY_BUILD_ID") or "v30-local")[:12]
protected={x.strip() for x in os.getenv("PROTECTED_CODES","").split(",") if x.strip()}
cache_lock=threading.Lock()
started=False
coin_settings_lock=threading.RLock()
coin_budget_explicit=None
coin_auto_max_if_unset=True
coin_reentry_until={}

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

def _paper_payload():
    return {
        "cash_krw":paper.cash_krw,"budget_day":paper.budget_day,
        "explicit_budget_krw":paper.explicit_budget_krw,"auto_max_if_unset":paper.auto_max_if_unset,
        "positions":[{
            "market":p.market,"code":p.code,"name":p.name,"qty":p.qty,"avg_price":p.avg_price,
            "current_price":p.current_price,"fx_buy":p.fx_buy,"fx_current":p.fx_current,
            "strategy":p.strategy,"entry_session":p.entry_session,"entry_ts":p.entry_ts,
        } for p in paper.positions.values()],
        "trades":paper.trades[:1000],
    }

def _persist_paper():
    store.save_json("paper_account",_paper_payload())

def _restore_paper():
    data=store.load_json("paper_account",None)
    if not isinstance(data,dict):return
    try:
        paper.cash_krw=float(data.get("cash_krw",paper.initial_cash_krw))
        paper.budget_day=str(data.get("budget_day") or "")
        paper.explicit_budget_krw=data.get("explicit_budget_krw")
        paper.auto_max_if_unset=bool(data.get("auto_max_if_unset",paper.auto_max_if_unset))
        paper.positions.clear()
        for x in data.get("positions") or []:
            pos=Position(str(x["market"]),str(x["code"]),str(x.get("name") or x["code"]),int(x["qty"]),
                         float(x["avg_price"]),float(x.get("current_price") or x["avg_price"]),
                         float(x.get("fx_buy") or 1),float(x.get("fx_current") or 1),
                         str(x.get("strategy") or "SCALP"),str(x.get("entry_session") or ""),float(x.get("entry_ts") or 0))
            paper.positions[pos.key]=pos
        paper.trades=list(data.get("trades") or [])[:1000]
    except Exception as exc:
        print("PAPER RESTORE ERROR:",exc,flush=True)

def _persist_coin():
    store.save_json("coin_paper_account",coin_paper.payload())

def _restore_coin():
    data=store.load_json("coin_paper_account",None)
    if isinstance(data,dict):
        try:coin_paper.restore(data)
        except Exception as exc:print("COIN PAPER RESTORE ERROR:",exc,flush=True)

def _persist_coin_settings():
    with coin_settings_lock:
        store.save_json("coin_settings",{
            "explicit_budget_krw":coin_budget_explicit,
            "auto_max_if_unset":coin_auto_max_if_unset,
        })

def _restore_coin_settings():
    global coin_budget_explicit,coin_auto_max_if_unset
    data=store.load_json("coin_settings",None)
    if not isinstance(data,dict):return
    with coin_settings_lock:
        raw=data.get("explicit_budget_krw")
        coin_budget_explicit=None if raw is None else max(0,min(coin_paper.initial_cash_krw,int(raw)))
        coin_auto_max_if_unset=bool(data.get("auto_max_if_unset",True))

def coin_effective_budget():
    with coin_settings_lock:
        if coin_budget_explicit is None:
            return coin_paper.initial_cash_krw if coin_auto_max_if_unset else 0
        return max(0,min(coin_paper.initial_cash_krw,int(coin_budget_explicit)))

def coin_available_budget():
    cap=coin_effective_budget()
    held=coin_paper.held_cost_krw()
    return max(0.0,min(float(coin_paper.cash_krw),float(cap)-float(held)))

def normalize_market(v):
    m=str(v).upper()
    if m=="US":return "US"
    if m=="COIN":return "COIN"
    return "KR"
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

def _clamp(v,lo=0.0,hi=100.0):
    return max(lo,min(hi,float(v or 0)))

def build_sector_context(market):
    groups={}
    for q in list(feed.quotes_for(market).values()):
        if q.price<=0 or q.open<=0:continue
        sec=sector_name(q,market);groups.setdefault(sec,[]).append(q)
    sectors=[];stock_strength={}
    for sec,qs in groups.items():
        changes=[(q.price/q.open-1)*100 for q in qs if q.open>0]
        avg=sum(changes)/len(changes) if changes else 0
        breadth=sum(x>0 for x in changes)/len(changes)*100 if changes else 0
        vols=[_vol_ratio(q) for q in qs if _vol_ratio(q)>0]
        avg_vol=sum(vols)/len(vols) if vols else 0
        # Convert investor net quantities into an approximate flow value so a
        # 1-share high-price stock and a 1-share low-price stock are comparable.
        fval=sum(q.price*max(0,float(q.foreign_net or 0)) for q in qs) if market=="KR" else 0
        ival=sum(q.price*max(0,float(q.institution_net or 0)) for q in qs) if market=="KR" else 0
        pval=sum(q.price*max(0,float(q.program_net or 0)) for q in qs) if market=="KR" else 0
        person_exit=sum(q.price*max(0,-float(getattr(q,"person_net",0) or 0)) for q in qs) if market=="KR" else 0
        f=sum(q.foreign_net for q in qs) if market=="KR" else 0
        i=sum(q.institution_net for q in qs) if market=="KR" else 0
        p=sum(q.program_net for q in qs) if market=="KR" else 0
        person=sum(float(getattr(q,"person_net",0) or 0) for q in qs) if market=="KR" else 0
        money=sum(q.price*q.volume for q in qs)
        turnover_sorted=sorted(q.price*q.volume for q in qs)

        leader=None;leader_strength=-1.0
        for q in qs:
            ch=((q.price/q.open)-1)*100 if q.open else -10
            vr=_vol_ratio(q);turn=q.price*q.volume
            pct_rank=((turnover_sorted.index(turn)+1)/len(turnover_sorted)) if turnover_sorted else 0
            momentum=_clamp((ch+1.0)/7.0*25,0,25)
            volume_score=_clamp(vr/200*20,0,20)
            turnover_score=20*pct_rank
            execution=_clamp((float(q.execution_strength or 0)-80)/70*15,0,15) if market=="KR" else 7.5
            flow_dirs=sum(x>0 for x in (q.foreign_net,q.institution_net,q.program_net)) if market=="KR" else 1
            flow_score=5*flow_dirs
            relative=_clamp((ch-avg+1)/4*5,0,5)
            strength=_clamp(momentum+volume_score+turnover_score+execution+flow_score+relative)
            q.leader_strength=round(strength,1)
            if strength>leader_strength:leader=q;leader_strength=strength
        leader=leader or qs[0]
        leader_change=((leader.price/leader.open)-1)*100 if leader.open else 0
        leader_vr=_vol_ratio(leader)

        if market=="KR":
            direction=(1.5 if f>0 else 0)+(1.5 if i>0 else 0)+(1.0 if p>0 else 0)
            score=direction+min(2,max(0,(breadth-40)/30))+min(2,max(0,(avg_vol-30)/70*2))+min(2,max(0,(avg+0.5)*1.2))
        else:
            score=min(10,max(0,(avg+1)*2.2)+(1 if money>0 else 0))
        score=round(max(0,min(10,score)),1)
        sectors.append({
            "sector":sec,"change_pct":avg,"score":score,"strength_score":round(score*10,1),
            "leader":leader.name or leader.code,"leader_code":leader.code,"leader_strength":round(leader_strength,1),
            "leader_change_pct":leader_change,"leader_volume_ratio":leader_vr,
            "foreign_net":f if market=="KR" else None,"institution_net":i if market=="KR" else None,
            "program_net":p if market=="KR" else None,"person_net":person if market=="KR" else None,
            "flow_value":{"foreign":fval,"institution":ival,"program":pval,"person_exit":person_exit},
            "volume_ratio":avg_vol,"breadth":breadth,"live_count":len(qs),
            "catalog_count":len(feed.sector_catalog.get(sec,[])) if market=="KR" else len(qs),
        })
        sorted_vol=sorted(qs,key=_vol_ratio)
        for q in qs:
            vrank=(sorted_vol.index(q)+1)/len(sorted_vol) if sorted_vol else 0
            if market=="KR":
                dirs=sum(x>0 for x in (q.foreign_net,q.institution_net,q.program_net))/3
                leader_bonus=float(getattr(q,"leader_strength",0))/100
                ss=2.0*vrank+2.0*dirs+1.0*leader_bonus
            else:ss=2.5*vrank
            stock_strength[q.code]=round(max(0,min(5,ss)),1)

    # Every flow tab is independently normalized to 100. Program flow is not
    # added as literal money to foreign/institution because the groups overlap.
    if market=="KR" and sectors:
        totals={k:sum(max(0,float(x["flow_value"][k] or 0)) for x in sectors) for k in ("foreign","institution","program","person_exit")}
        for x in sectors:
            shares={k:(x["flow_value"][k]/totals[k]*100 if totals[k]>0 else 0.0) for k in totals}
            composite_raw=(shares["foreign"]*0.35+shares["institution"]*0.35+shares["program"]*0.20+shares["person_exit"]*0.10)
            x["flow_share"]={**{k:round(v,1) for k,v in shares.items()},"composite_raw":composite_raw}
        comp_total=sum(x["flow_share"]["composite_raw"] for x in sectors)
        for x in sectors:
            x["flow_share"]["composite"]=round(x["flow_share"]["composite_raw"]/comp_total*100,1) if comp_total>0 else 0.0
            x["flow_share"].pop("composite_raw",None)
    else:
        for x in sectors:x["flow_share"]={"composite":round(100/len(sectors),1) if sectors else 0}
    sectors.sort(key=lambda x:(x.get("flow_share",{}).get("composite",0),x["score"]),reverse=True)
    return sectors[:24],{x["sector"]:x["score"] for x in sectors},stock_strength

def _smart14_analysis(q):
    base=smart_analysis(q)
    rows=list(getattr(q,"investor_daily",[]) or [])[-14:]
    if len(rows)<5:
        out=dict(base);out["investor_14d"]={"days":len(rows),"ready":False}
        out["reasons"]=list(base.get("reasons") or [])+[f"14거래일 수급 축적 {len(rows)}/14"]
        return out
    def acc(which):
        vals=[float(r.get(which,0) or 0) for r in rows]
        total=sum(vals);positive=sum(v>0 for v in vals)/len(vals)
        pts=0.0
        if total>0:
            pts=15+8*positive
            recent=sum(vals[-5:]);prev=sum(vals[-10:-5]) if len(vals)>=10 else sum(vals[:-5])
            if recent>=prev:pts+=7
        return round(min(30,max(0,pts)),1),total,positive
    foreign,fsum,fpos=acc("foreign");institution,isum,ipos=acc("institution")
    prog_vals=[float(r.get("program",0) or 0) for r in rows];psum=sum(prog_vals)
    prog=0.0
    if psum>0:
        prog=7.0
        if sum(prog_vals[-5:])>=sum(prog_vals[-10:-5]):prog=10.0
    persons=[float(r.get("person",0) or 0) for r in rows];person_sum=sum(persons)
    person_bonus=0.0
    if fsum>0 and isum>0 and person_sum<0:
        person_bonus=2.0
        if sum(v<0 for v in persons)/len(persons)>=0.60:person_bonus+=1.0
        if sum(persons[-5:])<sum(persons[-10:-5]):person_bonus+=1.0
        if sum(float(r.get("foreign",0) or 0)+float(r.get("institution",0) or 0) for r in rows[-5:])>0:person_bonus+=1.0
    b=base.get("breakdown",{})
    score=foreign+institution+prog+float(b.get("가격위치",0))+float(b.get("엘리어트",0))+float(b.get("가치",0))+person_bonus
    reasons=[
        f"14일 외국인 매집 +{foreign:.1f}",f"14일 기관 매집 +{institution:.1f}",f"14일 프로그램 +{prog:.1f}",
        f"14일 개인 {'순매도' if person_sum<0 else '순매수'} {abs(person_sum):,.0f}주 · 보너스 +{person_bonus:.1f}",
    ]+[r for r in base.get("reasons",[]) if not (r.startswith("외국인 매집") or r.startswith("기관 매집") or r.startswith("프로그램"))]
    return {
        "score":round(min(100,max(0,score)),1),"reasons":reasons,
        "breakdown":{**b,"외국인매집":foreign,"기관매집":institution,"프로그램":prog,"개인이탈":person_bonus},
        "investor_14d":{"days":len(rows),"ready":len(rows)>=14,"foreign_sum":fsum,"institution_sum":isum,
                        "program_sum":psum,"person_sum":person_sum,"foreign_positive_ratio":round(fpos*100,1),
                        "institution_positive_ratio":round(ipos*100,1),"person_exit_bonus":person_bonus},
    }

def candidate(q,market,smart=False,secmap=None,stockmap=None,leadermap=None,sector_rankmap=None,now=None):
    sec=sector_name(q,market)
    if smart:
        a=_smart14_analysis(q)
        eligible,rank,elig_reason=smart_buy_eligibility(q,now)
    else:
        a=scalp_analysis(q,(secmap or {}).get(sec,0),(stockmap or {}).get(q.code,0),market,now)
        eligible=rank=None;elig_reason=""
    vi_pre=q.open*1.10*0.997 if market=="KR" and q.open else None
    is_leader=(leadermap or {}).get(sec)==q.code if not smart else False
    sector_score=float((secmap or {}).get(sec,0) or 0)
    sector_rank=(sector_rankmap or {}).get(sec)
    # Priority affects scan/order only. The raw strategy score and 72-point entry threshold stay unchanged.
    leader_strength=float(getattr(q,"leader_strength",0) or 0)
    priority_score=(float(a["score"])+(6.0 if is_leader else 0.0)+min(4.0,sector_score*0.40)+leader_strength*0.04) if not smart else float(a["score"])
    reasons=list(a["reasons"])
    if is_leader:
        reasons.insert(0,"섹터 대장주 우선 감지")
    return {
        "market":market,"code":q.code,"name":q.name or q.code,"sector":sec,
        "currency":"KRW" if market=="KR" else "USD",
        "price":krw(q.price) if market=="KR" else round(float(q.price),4),
        "open":krw(q.open) if market=="KR" else round(float(q.open),4),
        "score":a["score"],"priority_score":round(priority_score,1),"score_breakdown":a.get("breakdown",{}),"phase":a.get("phase",""),
        "sector_score":sector_score,"sector_rank":sector_rank,"is_sector_leader":is_leader,"leader_strength":round(leader_strength,1),
        "execution_strength":q.execution_strength,
        "per":q.per if smart else None,"pbr":q.pbr if smart else None,
        "foreign_net":q.foreign_net if market=="KR" else None,
        "institution_net":q.institution_net if market=="KR" else None,
        "program_net":q.program_net if market=="KR" else None,
        "volume_ratio":round(_vol_ratio(q),1) if q.prev_day_volume>0 else None,
        "vi_pre":krw(vi_pre) if vi_pre else None,
        "reasons":reasons,
        "series":[krw(x) if market=="KR" else round(float(x),4) for x in list(q.prices)[-24:]],
        "smart_buy_eligible":eligible if smart else None,
        "smart_close_rank":rank if smart else None,
        "smart_eligibility_reason":elig_reason if smart else None,
        "event":q.events[0] if q.events else None,"investor_14d":a.get("investor_14d") if smart else None,
    }

def rebuild_cache(market,now=None):
    market=normalize_market(market)
    sectors,secmap,stockmap=build_sector_context(market)
    leadermap={x["sector"]:x.get("leader_code") for x in sectors if x.get("leader_code")}
    sector_rankmap={x["sector"]:i+1 for i,x in enumerate(sectors)}
    quotes=[q for q in feed.quotes_for(market).values() if q.price>0]
    scalp=[];smart=[]
    for q in quotes:
        try:
            scalp.append(candidate(q,market,False,secmap,stockmap,leadermap,sector_rankmap,now))
            if market=="KR":smart.append(candidate(q,market,True,now=now))
        except Exception:
            continue
    # Keep the 72-point gate intact. Among valid candidates, strong-sector leaders are scanned first.
    scalp.sort(key=lambda x:(x["score"]>=72,x.get("priority_score",x["score"]),x["score"]),reverse=True)
    smart.sort(key=lambda x:x["score"],reverse=True)
    stamp=(now or datetime.now(KST)).astimezone(KST) if isinstance((now or datetime.now(KST)),datetime) else datetime.now(KST)
    minute=stamp.strftime("%Y%m%d%H%M")
    for strategy,items in (("SCALP",scalp[:12]),("SMART",smart[:12] if market=="KR" else [])):
        for item in items:
            if float(item.get("score",0))<72:continue
            payload={k:item.get(k) for k in ("market","code","name","sector","price","score","priority_score","score_breakdown","is_sector_leader","leader_strength","investor_14d")}
            store.record_signal(f"{market}:{strategy}:{item['code']}:{minute}",market,strategy,item["code"],payload,stamp.timestamp())
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
    # KR VI pre-line is the same conservative threshold used by the entry filter.
    # If that line is closer than the normal +3% target, take profit there first.
    item_map={x["code"]:x for x in scalp_candidates}
    item_map.update({x["code"]:x for x in smart_candidates})
    for p in list(paper.market_positions(market)):
        q=quotes.get(p.code)
        if not q or q.price<=0:continue
        paper.mark(market,p.code,q.price,fx)
        score=(smart_map if p.strategy=="SMART" else scalp_map).get(p.code,50)
        reason=""
        vi_pre=None
        if market=="KR":
            vi_pre=(item_map.get(p.code) or {}).get("vi_pre")
        vi_take=bool(
            market=="KR"
            and vi_pre
            and float(vi_pre)>float(p.avg_price)
            and float(vi_pre)<=float(p.avg_price)*1.03
            and float(q.price)>=float(vi_pre)
        )
        if market=="KR" and must_force_sell_pre(p,now):reason="08:49 프리세션 강제청산"
        elif vi_take:reason="VI 직전 익절"
        elif p.pnl_pct>=3.0:reason="목표수익 +3% 도달"
        elif p.pnl_pct<=-1.5:reason="손절 기준 도달"
        elif score<46:reason="AI 점수 이탈"
        if reason:
            if paper.sell(market,p.code,q.price,fx,reason):_persist_paper()

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
    ok=paper.buy(q,qty,market,fx,day,strategy=strategy,entry_session=entry_session) is not None
    if ok:_persist_paper()
    return ok

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
        fresh,_=feed.entry_data_status(market,code,now.timestamp())
        if not fresh:continue
        if _buy_one(market,item,"SCALP",session,now):break

def trade_smart_kr(candidates,now=None):
    now=(now or datetime.now(KST)).astimezone(KST)
    if not smart_buy_window(now):return
    for item in candidates:
        if len(paper.market_positions("KR"))>=3 or item["score"]<72:break
        if not item.get("smart_buy_eligible"):continue
        code=item["code"]
        if code in protected or f"KR:{code}" in paper.positions:continue
        fresh,_=feed.entry_data_status("KR",code,now.timestamp())
        if not fresh:continue
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

def coin_ai_loop():
    while True:
        try:
            now=time.time()
            candidates=coin_feed.candidates(max(40,coin_feed.top_n))
            score_map={str(x.get("code") or "").upper():x for x in candidates}
            changed=False
            for p in list(coin_paper.positions.values()):
                q=coin_feed.quote(p.symbol)
                if not q or q.price<=0:continue
                coin_paper.mark(p.symbol,q.price)
                reason=""
                if p.pnl_pct>=3.0:reason="익절 +3%"
                elif p.pnl_pct<=-1.5:reason="손절 -1.5%"
                else:
                    item=score_map.get(p.symbol)
                    if item is not None and float(item.get("score") or 0)<46:reason="점수 46 미만"
                if reason:
                    if coin_paper.sell(p.symbol,q.price,reason):
                        coin_reentry_until[p.symbol]=now+300
                        changed=True
            if changed:_persist_coin()

            budget=coin_effective_budget()
            if budget>=10_000 and coin_feed.connected and len(coin_paper.positions)<3:
                for item in candidates:
                    if float(item.get("score") or 0)<72:break
                    symbol=str(item.get("code") or "").upper()
                    if not symbol or f"COIN:{symbol}" in coin_paper.positions:continue
                    if coin_reentry_until.get(symbol,0)>now:continue
                    if float(item.get("fresh_age") or 9999)>30:continue
                    if float(item.get("quote_volume") or 0)<1_000_000_000:continue
                    q=coin_feed.quote(symbol)
                    if not q or q.price<=0:continue
                    available=coin_available_budget()
                    if available<10_000:break
                    per_position=max(10_000,float(budget)/3.0)
                    spend=min(per_position,available)
                    if coin_paper.buy(q,spend,"COIN_SCALP"):
                        _persist_coin()
                        break
        except Exception as exc:
            print("COIN AI LOOP ERROR:",str(exc)[:180],flush=True)
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

def coin_feed_diagnostic():
    # One concise boot-time line so Render logs can confirm Coinone connectivity.
    time.sleep(8)
    try:
        h=coin_feed.health()
        print(
            f"COINONE STATUS rest={bool(h.get('rest_connected'))} "
            f"ws={bool(h.get('ws_connected'))} priced={int(h.get('priced_count') or 0)} "
            f"markets={int(h.get('market_count') or 0)} "
            f"error={(h.get('error') or h.get('ws_error') or '-')[:120]}",
            flush=True,
        )
    except Exception as exc:
        print("COINONE STATUS ERROR:",str(exc)[:160],flush=True)

def start_background():
    global started
    if started:return
    started=True
    _restore_paper()
    _restore_coin()
    _restore_coin_settings()
    coin_feed.start()
    threading.Thread(target=coin_feed_diagnostic,daemon=True).start()
    if os.getenv("NHPLUG_APP_KEY") and os.getenv("NHPLUG_APP_SECRET"):
        threading.Thread(target=nh_feed_bootstrap,daemon=True).start()
    threading.Thread(target=ai_loop,daemon=True).start()
    threading.Thread(target=coin_ai_loop,daemon=True).start()
    events.start()

@asynccontextmanager
async def lifespan(_app):
    start_background();yield

app=FastAPI(title="GY 모의투자 시스템",lifespan=lifespan)
app.mount("/static",StaticFiles(directory="static"),name="static")

@app.middleware("http")
async def gy_headers(request,call_next):
    response=await call_next(request)
    if request.url.path=="/" or request.url.path.startswith("/coin") or request.url.path.startswith("/static/"):
        response.headers["Cache-Control"]="no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"]="no-cache"
    response.headers["X-GY-Build"]=BUILD_ID
    return response

@app.get("/")
def home():
    return FileResponse("static/index.html",headers={"Cache-Control":"no-store, max-age=0"})

@app.get("/coin")
def coin_home():
    return FileResponse("static/coin.html",headers={"Cache-Control":"no-store, max-age=0"})

@app.get("/coin/{symbol}")
def coin_page(symbol:str):
    symbol=str(symbol).upper()
    if not re.fullmatch(r"[A-Z0-9._-]{1,20}",symbol):raise HTTPException(404)
    return FileResponse("static/coin-detail.html",headers={"Cache-Control":"no-store, max-age=0"})

INDEX_KEYS={
    "KR":{"kospi","kosdaq","kospi_night","nasdaq_future","sox"},
    "US":{"sp500","nasdaq","nasdaq_future","sox"},
}

@app.get("/index/{market}/{key}")
def index_page(market:str,key:str):
    market=normalize_market(market);key=str(key).lower()
    if market not in INDEX_KEYS or key not in INDEX_KEYS[market]:raise HTTPException(404,"index not available in this market mode")
    return FileResponse("static/index-detail.html",headers={"Cache-Control":"no-store, max-age=0"})

@app.get("/stock/{market}/{code}")
def stock_page(market:str,code:str):
    market=normalize_market(market)
    if market not in ("KR","US"):raise HTTPException(404)
    if market=="KR" and not re.fullmatch(r"\d{6}",code):raise HTTPException(404)
    if market=="US" and not re.fullmatch(r"[A-Za-z0-9.\-]{1,12}",code):raise HTTPException(404)
    return FileResponse("static/stock.html",headers={"Cache-Control":"no-store, max-age=0"})

def health_payload():
    h=feed.health();ch=coin_feed.health()
    return {"ok":True,"nh_configured":bool(os.getenv("NHPLUG_APP_KEY") and os.getenv("NHPLUG_APP_SECRET")),
            "nh_realtime":h["nh_realtime"],"realtime":h["realtime"],"errors":h["errors"],"orders_sent":0,
            "kr_tracked":h["kr_tracked"],"kr_priced":h["kr_priced"],"us_tracked":h["us_tracked"],"us_priced":h["us_priced"],
            "market_updated_at":h["market_updated_at"],"market_errors":h["market_errors"],"usdkrw":h["usdkrw"],
            "usdkrw_asof":h["usdkrw_asof"],"program_realtime":h.get("program_realtime",{}),
            "investor_updated_at":h.get("investor_updated_at",0),"history_updated_at":h.get("history_updated_at",0),
            "future_symbols":h.get("future_symbols",{}),"market_daily_error":h.get("market_daily_error",{}),
            "krx_openapi_configured":h.get("krx_openapi_configured",False),"sector_catalog_count":h.get("sector_catalog_count",0),
            "sector_scan_count":h.get("sector_scan_count",0),"sector_universe_asof":h.get("sector_universe_asof",""),
            "coinone":ch,"coin_paper_initial_cash":coin_paper.initial_cash_krw,
            "persistence":store.status(),"signal_count_30d":store.recent_signal_count(30),"build":BUILD_ID,"schedule":schedule_payload()}

@app.get("/api/health")
def health():return health_payload()

class BudgetRequest(BaseModel):
    amount:Optional[int]=None
    auto_max_if_unset:bool=True

@app.post("/api/budget")
def set_budget(data:BudgetRequest):
    active=trading_window() or default_view_market();day=trading_day_key(active)
    paper.set_auto_max(data.auto_max_if_unset);paper.set_budget(data.amount,day);_persist_paper()
    return {"ok":True,"budget_day":paper.budget_day,"explicit_budget":paper.explicit_budget_krw,
            "auto_max_if_unset":paper.auto_max_if_unset,"effective_budget":paper.effective_budget_krw(day),
            "initial_cash":paper.initial_cash_krw}

@app.post("/api/coin/budget")
def set_coin_budget(data:BudgetRequest):
    global coin_budget_explicit,coin_auto_max_if_unset
    amount=data.amount
    if amount is not None and (amount<0 or amount>coin_paper.initial_cash_krw):
        raise HTTPException(400,f"coin budget must be 0~{coin_paper.initial_cash_krw}")
    with coin_settings_lock:
        coin_budget_explicit=None if amount is None else int(amount)
        coin_auto_max_if_unset=bool(data.auto_max_if_unset)
    _persist_coin_settings()
    return {"ok":True,"explicit_budget":coin_budget_explicit,
            "auto_max_if_unset":coin_auto_max_if_unset,"effective_budget":coin_effective_budget(),
            "available_budget":krw(coin_available_budget()),"initial_cash":coin_paper.initial_cash_krw}

def paper_state(market):
    active=trading_window() or default_view_market();day=trading_day_key(active)
    # Account summary is global. Market switching changes analysis context only;
    # holdings/profit always represent the combined KR + US (+ future COIN) book.
    pos=[]
    for p in paper.positions.values():
        pos.append({"market":p.market,"code":p.code,"name":p.name,"qty":p.qty,"avg_price":p.avg_price,
                    "current_price":p.current_price,"currency":"USD" if p.market=="US" else "KRW",
                    "fx_buy":p.fx_buy if p.market=="US" else None,"fx_current":p.fx_current if p.market=="US" else None,
                    "cost_krw":krw(p.cost_krw),"value_krw":krw(p.value_krw),"pnl":krw(p.pnl_krw),"pnl_pct":p.pnl_pct,
                    "strategy":p.strategy,"entry_session":p.entry_session})
    pos.sort(key=lambda x:(x.get("market",""),x.get("name",""),x.get("code","")))
    trades=list(paper.trades)[:300]
    return {"initial_cash":paper.initial_cash_krw,"cash":krw(paper.cash_krw),"equity":krw(paper.equity_krw()),
            "budget_day":paper.budget_day,"explicit_budget":paper.explicit_budget_krw,
            "budget":paper.effective_budget_krw(day),"effective_budget":paper.effective_budget_krw(day),
            "auto_max_if_unset":paper.auto_max_if_unset,"held_cost":krw(paper.held_cost_krw()),
            "market_held_cost":krw(paper.held_cost_krw(market)),"positions":pos,"trades":trades,
            "account_scope":"ALL","auto_trade_enabled":trading_window()==market,
            "usdkrw":feed.usdkrw,"usdkrw_asof":feed.usdkrw_asof}

def coin_account_state():
    for p in list(coin_paper.positions.values()):
        q=coin_feed.quote(p.symbol)
        if q and q.price>0:coin_paper.mark(p.symbol,q.price)
    positions=[]
    for p in coin_paper.positions.values():
        positions.append({"market":"COIN","code":p.symbol,"name":p.name,"qty":p.qty,"avg_price":p.avg_price,
                          "current_price":p.current_price,"currency":"KRW","cost_krw":krw(p.cost_krw),
                          "value_krw":krw(p.value_krw),"pnl":krw(p.pnl_krw),"pnl_pct":p.pnl_pct,
                          "strategy":p.strategy,"entry_session":"24H"})
    positions.sort(key=lambda x:(x.get("name",""),x.get("code","")))
    equity=coin_paper.equity_krw()
    return {"initial_cash":coin_paper.initial_cash_krw,"cash":krw(coin_paper.cash_krw),"equity":krw(equity),
            "budget":coin_effective_budget(),"effective_budget":coin_effective_budget(),
            "explicit_budget":coin_budget_explicit,"auto_max_if_unset":coin_auto_max_if_unset,
            "available_budget":krw(coin_available_budget()),
            "held_cost":krw(coin_paper.held_cost_krw()),"market_held_cost":krw(coin_paper.held_cost_krw()),
            "positions":positions,"trades":list(coin_paper.trades)[:300],"account_scope":"COIN_ONLY",
            "auto_trade_enabled":coin_effective_budget()>=10000 and coin_feed.connected,
            "unrealized_pnl":krw(coin_paper.unrealized_pnl_krw()),
            "total_pnl":krw(equity-coin_paper.initial_cash_krw),"exchange":"Coinone"}

def global_account_state():
    stock_equity=paper.equity_krw();coin_equity=coin_paper.equity_krw()
    return {"initial_cash":krw(paper.initial_cash_krw+coin_paper.initial_cash_krw),
            "equity":krw(stock_equity+coin_equity),
            "pnl":krw((stock_equity-paper.initial_cash_krw)+(coin_equity-coin_paper.initial_cash_krw)),
            "stock_equity":krw(stock_equity),"coin_equity":krw(coin_equity),
            "stock_cash":krw(paper.cash_krw),"coin_cash":krw(coin_paper.cash_krw),
            "stock_initial_cash":paper.initial_cash_krw,"coin_initial_cash":coin_paper.initial_cash_krw,
            "account_separation":True}

def market_separation_check(market,scalp,smart,positions):
    codes=[str(x.get("code","")) for x in scalp+smart+positions]
    bad=[c for c in codes if (re.fullmatch(r"\d{6}",c) if market=="US" else (c and not re.fullmatch(r"\d{6}",c)))]
    return {"ok":not bad,"market":market,"bad_codes":sorted(set(bad))}

@app.get("/api/state")
def state(market:str=Query("KR")):
    market=normalize_market(market)
    if market=="COIN":
        candidates=coin_feed.candidates(30)
        return {"mode":"COIN","health":health_payload(),
                "market":{"exchange":"Coinone","quote_currency":"KRW","open":True,"status":"24시간 거래",
                          "updated_at":coin_feed.updated_at,"source":"Coinone Public API"},
                "session":{"name":"Coinone","label":"24시간 거래","open":True,"status":"거래중"},
                "sectors":[],"scalp":candidates,"smart":[],"candidate_scan_active":True,
                "macro_events":[],"events":{"items":[]},"cache_updated_at":coin_feed.updated_at,
                "paper":coin_account_state(),"global_account":global_account_state(),"build":BUILD_ID,
                "sector_coverage":{"catalog":0,"live":len(candidates),"asof":""},
                "protected_codes":[],"market_separation":{"ok":True,"market":"COIN","bad_codes":[]}}
    scan_active=trading_window()==market
    with cache_lock:
        c=CACHE[market];sectors=list(c["sectors"]);updated=c["updated_at"]
        # Keep the analysis cache warm in the background, but do not fill the
        # closed-market dashboard with zero/stale candidate cards.
        scalp=list(c["scalp"][:30]) if scan_active else []
        smart=(list(c["smart"][:30]) if market=="KR" and scan_active else [])
    ps=paper_state(market)
    sep_positions=[p for p in ps["positions"] if p.get("market")==market]
    sep=market_separation_check(market,scalp,smart,sep_positions)
    return {"mode":market,"health":health_payload(),"schedule":schedule_payload(),"market":feed.market_state(market),
            "session":feed.session_state(market),"sectors":sectors,"scalp":scalp,"smart":smart,
            "candidate_scan_active":scan_active,"macro_events":macro_calendar_payload(),
            "events":events.state(market),"cache_updated_at":updated,"paper":ps,"global_account":global_account_state(),"build":BUILD_ID,
            "sector_coverage":{"catalog":health_payload().get("sector_catalog_count",0),"live":health_payload().get("sector_scan_count",0),
                               "asof":health_payload().get("sector_universe_asof","")},
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
    if market not in ("KR","US"):raise HTTPException(404,"stock market only")
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
                "program_net":q.program_net if market=="KR" else None,"person_net":getattr(q,"person_net",None) if market=="KR" else None,
                "execution_strength":q.execution_strength if market=="KR" else None,
                "volume_ratio":round(_vol_ratio(q),1) if q.prev_day_volume>0 else None},
        "events":q.events if market=="KR" else [],
        "daily_bars":list(q.daily_bars)[-30:],"investor_14d":list(getattr(q,"investor_daily",[]) or [])[-14:] if market=="KR" else [],
    }

@app.get("/api/sector/{market}/{sector:path}")
def sector_detail(market:str,sector:str):
    market=normalize_market(market)
    if market not in ("KR","US"):raise HTTPException(404,"sector not available in this market mode")
    with cache_lock:
        summary=next((x for x in CACHE[market]["sectors"] if x.get("sector")==sector),None)
    if market=="KR":
        members=feed.sector_members(sector)
    else:
        members=[]
        for q in feed.quotes_for("US").values():
            if sector_name(q,"US")==sector:
                members.append({"code":q.code,"name":q.name or q.code,"live":q.price>0,"price":q.price,
                                "change_pct":((q.price/q.open)-1)*100 if q.open else None,"volume_ratio":_vol_ratio(q)})
    return {"market":market,"sector":sector,"summary":summary,"members":members,"count":len(members),"build":BUILD_ID}

@app.get("/api/index/{market}/{key}")
def index_detail(market:str,key:str,timeframe:str=Query("1d")):
    market=normalize_market(market);key=str(key).lower();tf=str(timeframe).lower()
    if market not in INDEX_KEYS or key not in INDEX_KEYS[market]:raise HTTPException(404,"index not available in this market mode")
    if tf not in ("1d","d","day"):
        raise HTTPException(400,"index chart supports daily data only")
    item=feed.market_item(key)
    if not item:raise HTTPException(404,"index data not ready")
    # Never make the browser wait on a live KRX fetch. KOSPI/KOSDAQ daily
    # history is prefetched by NHFeed in a dedicated background loop.
    bars=feed.market_bars(key,"1d")
    daily_error=getattr(feed,"market_daily_error",{}).get(key,"")
    daily_source=getattr(feed,"market_daily_source",{}).get(key,"")
    if key in ("kospi","kosdaq") and not bars:
        note=daily_error or "KRX 1D 데이터 수신 대기"
    else:
        note=f"1D OHLC · {daily_source or item.get('source','공식 데이터')} · 최근 거래일 기준"
    return {
        "market":market,"key":key,"label":item.get("label",key),"value":item.get("value"),
        "change":item.get("change"),"change_pct":item.get("change_pct"),"status":item.get("status",""),
        "source":item.get("source",""),"daily_source":daily_source,"asof":item.get("asof",""),"timeframe":"1d","bars":bars,
        "market_open":feed.market_open_for_key(key),"note":note,"daily_error":daily_error,"build":BUILD_ID,
    }

@app.get("/api/coin/state")
def coin_state_api():
    account=coin_account_state()
    coin_pnl=krw(account.get("total_pnl",0))
    account["pnl"]=coin_pnl
    account["pnl_pct"]=(coin_pnl/account["initial_cash"]*100) if account.get("initial_cash") else 0.0
    account["max_positions"]=3
    overall=global_account_state()
    overall["pnl_pct"]=(overall["pnl"]/overall["initial_cash"]*100) if overall.get("initial_cash") else 0.0
    market=[]
    for q in coin_feed.top_quotes(12):
        market.append({
            "market":"COIN","code":q.symbol,"name":q.name or q.symbol,"price":q.price,
            "change_pct":q.change_pct,"quote_volume":q.quote_volume,"target_volume":q.target_volume,
            "volume_power":q.volume_power,"spread_pct":q.spread_pct,"book_imbalance":q.book_imbalance,
            "updated_at":q.updated_at,
        })
    return {
        "mode":"COIN","exchange":"Coinone","account":account,"overall":overall,
        "health":coin_feed.health(),"market":market,"candidates":coin_feed.candidates(30),
        "source":"Coinone Public API","real_orders_enabled":False,"build":BUILD_ID,
    }

@app.get("/api/coin/chart/{symbol}")
def coin_chart_api(symbol:str,interval:str=Query("1d"),size:int=Query(120,ge=20,le=500)):
    return coin_detail(symbol,interval,size)

@app.get("/api/coin/{symbol}")
def coin_detail(symbol:str,interval:str=Query("1d"),size:int=Query(120,ge=20,le=500)):
    symbol=str(symbol).upper()
    q=coin_feed.quote(symbol)
    if not q:
        try:coin_feed.refresh_rest();q=coin_feed.quote(symbol)
        except Exception:pass
    if not q:raise HTTPException(404,"coin not found on Coinone KRW market")
    try:bars=coin_feed.chart(symbol,interval,size)
    except Exception as exc:raise HTTPException(502,f"Coinone chart error: {str(exc)[:180]}")
    candidate=next((x for x in coin_feed.candidates(max(30,coin_feed.top_n)) if x.get("code")==symbol),None)
    return {"market":"COIN","exchange":"Coinone","code":symbol,"name":q.name or symbol,
            "price":q.price,"currency":"KRW","interval":interval,"bars":bars,"candidate":candidate,
            "change_pct":q.change_pct,"quote_volume":q.quote_volume,"target_volume":q.target_volume,
            "volume_power":q.volume_power,"ask_price":q.ask_price,"bid_price":q.bid_price,
            "spread_pct":q.spread_pct,"book_imbalance":q.book_imbalance,"updated_at":q.updated_at,
            "quote":{"change_pct":q.change_pct,"quote_volume":q.quote_volume,"target_volume":q.target_volume,
                     "volume_power":q.volume_power,"ask_price":q.ask_price,"bid_price":q.bid_price,
                     "spread_pct":q.spread_pct,"book_imbalance":q.book_imbalance,"updated_at":q.updated_at},
            "source":"Coinone Public API","real_orders_enabled":False,"build":BUILD_ID}

@app.get("/api/coin-account")
def coin_account():
    return {"paper":coin_account_state(),"global_account":global_account_state(),"health":coin_feed.health(),"build":BUILD_ID}

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
