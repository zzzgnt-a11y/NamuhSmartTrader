from __future__ import annotations
import html as html_lib
import os
import re
import threading
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable
from zoneinfo import ZoneInfo
import requests

from engine import Quote

KST=timezone(timedelta(hours=9))
KR_DEFAULT_CODES=["005930","000660","035420","035720","068270","012450","267260","042700","005380","000270","105560","055550","086790","028260","207940"]
US_DEFAULT_CODES=["AAPL","MSFT","NVDA","AMZN","META","GOOGL","TSLA","AVGO","AMD","NFLX","COST","PLTR","JPM","BAC","WMT","LLY","UNH","XOM","CVX","ORCL","CRM","ADBE","QCOM","MU","INTC","ARM","TSM"]
KR_THEME_OVERRIDES={
    "005930":"반도체","000660":"반도체","042700":"반도체",
    "035420":"인터넷/AI","035720":"인터넷/AI","068270":"바이오",
    "012450":"방산","267260":"전력기기","005380":"자동차","000270":"자동차",
    "105560":"금융","055550":"금융","086790":"금융","028260":"지주","207940":"바이오",
}
KOSPI200_SECTOR={"1":"건설기계","2":"중공업","3":"철강소재","4":"에너지화학","5":"정보통신",
                 "6":"금융","7":"생활소비재","8":"경기소비재","9":"산업재","A":"건강관리","B":"반도체"}

def walk(v):
    if isinstance(v,dict):
        yield v
        for x in v.values():yield from walk(x)
    elif isinstance(v,list):
        for x in v:yield from walk(x)

def num(v):
    try:return float(str(v).replace(",","").replace("+","").strip())
    except Exception:return 0.0

def pick(data,keys:Iterable[str]):
    for o in walk(data):
        for k in keys:
            if k in o and o[k] not in (None,""):return num(o[k])
    return 0.0

def pick_text(data,keys:Iterable[str]):
    for o in walk(data):
        for k in keys:
            if k in o and o[k] not in (None,""):return str(o[k]).strip()
    return ""

def first_list(data,keys=("Output_0","output_0","Output_1","output_1")):
    for o in walk(data):
        for k in keys:
            if isinstance(o.get(k),list):return o[k]
    return []

def dataframe_rows(frame):
    if frame is None:return []
    if hasattr(frame,"to_dict"):
        try:return frame.to_dict("records")
        except Exception:pass
    return frame if isinstance(frame,list) else []

def signed_value(value,sign):
    value=abs(num(value))
    return -value if str(sign) in ("4","5","8","9","-","▼") else value

def normalize_date(v):
    s=re.sub(r"\D","",str(v or ""))
    if len(s)>=8:
        if len(s)==8 and s[:2] in ("19","20"):return s[:8]
        if len(s)==8 and int(s[:2])<100:return "20"+s[:6]
        return s[:8]
    return ""

def parse_daily_rows(data, market="KR"):
    # NHPLUG endpoints do not all put history in the same output block.
    # KR currentDaily normally uses Output_0 while overseas period uses
    # Output_1. Parse every list and keep the richest dated OHLC series.
    candidates=[]
    for o in walk(data):
        if not isinstance(o,dict):continue
        for k in ("Output_0","output_0","Output_1","output_1","output"):
            rows=o.get(k)
            if not isinstance(rows,list):continue
            out=[];seen=set()
            for r in rows:
                if not isinstance(r,dict):continue
                date=normalize_date(r.get("bsop_date") or r.get("xymd") or r.get("date") or r.get("trade_date"))
                close=num(r.get("stck_clpr") or r.get("ovrs_prpr") or r.get("close_prc") or r.get("close") or r.get("trdprc"))
                if not date or close<=0 or date in seen:continue
                seen.add(date)
                out.append({
                    "date":date,
                    "open":num(r.get("stck_oprc") or r.get("ovrs_oprc") or r.get("open_prc") or r.get("open")) or close,
                    "high":num(r.get("stck_hgpr") or r.get("ovrs_hgpr") or r.get("high") or r.get("high_prc")) or close,
                    "low":num(r.get("stck_lwpr") or r.get("ovrs_lwpr") or r.get("low") or r.get("low_prc")) or close,
                    "close":close,
                    "volume":num(r.get("acml_vol") or r.get("acvol") or r.get("movolume") or r.get("volume") or r.get("vol")),
                })
            if out:
                out.sort(key=lambda x:x["date"])
                candidates.append(out)
    return max(candidates,key=len) if candidates else []

def aggregate_ticks(ticks,minutes=1):
    if not ticks:return []
    sec=max(1,int(minutes))*60
    buckets={}
    prev_cum=None
    for ts,price,cumvol in ticks:
        ts=float(ts);price=float(price);cumvol=float(cumvol or 0)
        b=int(ts//sec)*sec
        row=buckets.get(b)
        if row is None:
            row={"time":b,"open":price,"high":price,"low":price,"close":price,"volume":0.0}
            buckets[b]=row
        row["high"]=max(row["high"],price);row["low"]=min(row["low"],price);row["close"]=price
        if prev_cum is not None and cumvol>=prev_cum:
            row["volume"]+=cumvol-prev_cum
        prev_cum=cumvol
    return [buckets[k] for k in sorted(buckets)][-240:]

def aggregate_market_ticks(ticks,minutes=1):
    """Aggregate official snapshot values into runtime OHLC candles."""
    if not ticks:return []
    sec=max(1,int(minutes))*60;buckets={}
    for ts,value in ticks:
        ts=float(ts);value=float(value or 0)
        if value<=0:continue
        b=int(ts//sec)*sec;row=buckets.get(b)
        if row is None:
            row={"time":b,"open":value,"high":value,"low":value,"close":value,"volume":0.0};buckets[b]=row
        else:
            row["high"]=max(row["high"],value);row["low"]=min(row["low"],value);row["close"]=value
    return [buckets[k] for k in sorted(buckets)][-360:]


class NHFeed:
    def __init__(self):
        self.quotes:Dict[str,Dict[str,Quote]]={"KR":{},"US":{}}
        self.connected={"KR":False,"US":False}
        self.errors={"KR":"","US":""}
        self.scan_index={"KR":0,"US":0}
        self.code_lists={"KR":[],"US":[]}
        self.fixed={"KR":self._env_codes("TRACKED_CODES",KR_DEFAULT_CODES),
                    "US":self._env_codes("US_TRACKED_CODES",US_DEFAULT_CODES)}
        self.market={};self.market_errors={};self.market_updated_at=0.0
        self._usdkrw=0.0;self.usdkrw_asof="";self.usdkrw_source=""
        self.index_symbols={
            "sp500":os.getenv("NH_SP500_SYMBOL","").strip(),
            "nasdaq":os.getenv("NH_NASDAQ_SYMBOL","").strip(),
            "sox":os.getenv("NH_SOX_SYMBOL","").strip(),
        }
        self.future_symbols={
            "kospi_night":os.getenv("NH_KOSPI_NIGHT_SYMBOL","").strip(),
            "nasdaq_future":os.getenv("NH_NASDAQ_FUTURE_SYMBOL","").strip(),
            "nasdaq_future_exnm":os.getenv("NH_NASDAQ_FUTURE_EXNM","FCME").strip() or "FCME",
        }
        self.nxt={"session":"CLOSED","label":"NXT 장외시간","open":False,"updated_at":0.0}
        self.krx_series={"kospi":[],"kosdaq":[]}
        self.krx_http=requests.Session();self.krx_http_warmed_at=0.0;self.krx_logged_in=False
        self.krx_openapi_key=os.getenv("KRX_OPENAPI_KEY","").strip()
        self.market_daily_error={"kospi":"","kosdaq":""}
        self.kr_master_meta={}
        self.sector_catalog={}
        self.sector_scan_limit=max(15,min(500,int(os.getenv("KR_SECTOR_SCAN_LIMIT","160") or 160)))
        self.sector_scan_codes=list(self.fixed["KR"])
        self.sector_universe_asof=""
        # Official historical curves used when markets are closed so cards do
        # not turn into a repeated flat current-price line.
        self.future_history={"kospi_night":[],"nasdaq_future":[]}
        self.future_history_updated_at={"kospi_night":0.0,"nasdaq_future":0.0}
        self.daily_fetch_attempt_at={}
        market_keys=("kospi","kosdaq","sp500","nasdaq","sox","kospi_night","nasdaq_future")
        self.market_ticks={k:deque(maxlen=24000) for k in market_keys}
        self.market_daily_bars={k:deque(maxlen=120) for k in market_keys}
        self.market_daily_updated_at={k:0.0 for k in market_keys}
        self._stop=threading.Event()
        self.program_realtime={"connected":False,"error":"","updated_at":0.0}
        self.investor_updated_at=0.0
        self.history_updated_at=0.0

    @staticmethod
    def _env_codes(key,defaults):
        x=[v.strip().upper() for v in os.getenv(key,"").split(",") if v.strip()]
        return x or list(defaults)

    def quotes_for(self,market):
        return self.quotes["US" if str(market).upper()=="US" else "KR"]

    def connected_any(self):return any(self.connected.values())

    def q(self,market,code):
        market="US" if str(market).upper()=="US" else "KR";code=str(code).strip().upper()
        if code not in self.quotes[market]:self.quotes[market][code]=Quote(code,code)
        return self.quotes[market][code]

    # ----- index chart storage -----
    def market_open_for_key(self,key,now=None):
        key=str(key).lower();now=(now or datetime.now(KST)).astimezone(KST)
        if key in ("kospi","kosdaq"):
            m=now.hour*60+now.minute
            return now.weekday()<5 and 540<=m<=930
        if key in ("sp500","nasdaq","sox"):
            ny=now.astimezone(ZoneInfo("America/New_York"));m=ny.hour*60+ny.minute
            return ny.weekday()<5 and 570<=m<=960
        if key=="kospi_night":
            m=now.hour*60+now.minute
            if m>=1080:return now.weekday()<5
            if m<360:return (now-timedelta(days=1)).weekday()<5
            return False
        if key=="nasdaq_future":
            ny=now.astimezone(ZoneInfo("America/New_York"));m=ny.hour*60+ny.minute;wd=ny.weekday()
            if wd==5:return False
            if wd==6:return m>=1080
            if wd==4:return m<1020
            return not (1020<=m<1080)
        return False

    def _record_market_item(self,key,item):
        if not isinstance(item,dict):return
        self.market[key]=item
        v=num(item.get("value"))
        if v>0 and self.market_open_for_key(key):
            self.market_ticks.setdefault(key,deque(maxlen=24000)).append((time.time(),v))

    def _set_market_daily_bars(self,key,bars):
        clean=[];seen=set()
        for b in bars or []:
            d=normalize_date(b.get("date") or b.get("time"));c=num(b.get("close"))
            if not d or c<=0 or d in seen:continue
            seen.add(d);o=num(b.get("open")) or c;h=num(b.get("high")) or c;l=num(b.get("low")) or c
            clean.append({"time":d,"open":o,"high":h,"low":l,"close":c,"volume":num(b.get("volume"))})
        clean.sort(key=lambda x:x["time"]);q=self.market_daily_bars.setdefault(key,deque(maxlen=120));q.clear();q.extend(clean[-120:])
        if clean:self.market_daily_updated_at[key]=time.time()

    def market_bars(self,key,timeframe="1d"):
        key=str(key).lower();tf=str(timeframe).lower()
        if tf=="1d":return list(self.market_daily_bars.get(key,[]))[-60:]
        mins=3 if tf=="3m" else 1
        return aggregate_market_ticks(list(self.market_ticks.get(key,[])),mins)

    def market_item(self,key):
        return self.market.get(str(key).lower())

    # ----- NXT / FX -----
    def update_nxt_session(self,now=None):
        now=(now or datetime.now(KST)).astimezone(KST);mins=now.hour*60+now.minute+now.second/60
        if now.weekday()>=5:s,l,o="CLOSED","NXT 휴장",False
        elif 480<=mins<530:s,l,o="PRE","NXT 프리마켓",True
        elif 530<=mins<540.5:s,l,o="BREAK","NXT 메인마켓 대기",False
        elif 540.5<=mins<920:s,l,o="MAIN","NXT 메인마켓",True
        elif 920<=mins<940:s,l,o="AFTER_WAIT","NXT 애프터마켓 대기",False
        elif 940<=mins<1200:s,l,o="AFTER","NXT 애프터마켓",True
        else:s,l,o="CLOSED","NXT 장외시간",False
        self.nxt={"session":s,"label":l,"open":o,"updated_at":time.time()}

    def session_state(self,market):
        if str(market).upper()=="US":return None
        self.update_nxt_session()
        return {"name":"NXT",**self.nxt,"status":"거래중" if self.nxt["open"] else "대기/종료"}

    def _market_order(self):
        self.update_nxt_session()
        if self.nxt["session"] in ("PRE","AFTER"):return ("NXT","KRX")
        if self.nxt["session"]=="MAIN":return ("KRX","NXT")
        return ("KRX",)

    @staticmethod
    def _expected_us_trade_date(now=None):
        now=(now or datetime.now(KST)).astimezone(KST)
        if now.hour<6:now-=timedelta(days=1)
        return now.strftime("%Y%m%d")

    def _usdkrw_is_tradeable(self,now=None):
        a=str(self.usdkrw_asof or "")[:8]
        return 800<=self._usdkrw<=2500 and len(a)==8 and a.isdigit() and a==self._expected_us_trade_date(now)

    @property
    def usdkrw(self):return float(self._usdkrw) if self._usdkrw_is_tradeable() else 0.0
    @usdkrw.setter
    def usdkrw(self,v):self._usdkrw=num(v)
    @property
    def usdkrw_tradeable(self):return self._usdkrw_is_tradeable()

    def _update_us_fx_from_current(self,data):
        rate=pick(data,("currency_prc","fx_rate"));asof=pick_text(data,("trade_date","bsop_date","date"))[:8]
        unit=pick_text(data,("currency_unit","cur_cd")).upper()
        if unit and unit!="USD":return
        if 800<=rate<=2500 and len(asof)==8 and asof.isdigit():
            self._usdkrw=rate;self.usdkrw_asof=asof;self.usdkrw_source="NHPLUG 해외주식 현재가"

    # ----- current quote parsing -----
    def _apply_kr(self,code,data):
        q=self.q("KR",code)
        price=pick(data,("stck_prpr","prpr","price","cur_pr","now_pr"))
        volume=pick(data,("acml_vol","volume","vol"))
        prev=pick(data,("prdy_vol",))
        if prev>0:q.prev_day_volume=prev
        if price:q.mark(round(price),volume)
        q.open=round(pick(data,("stck_oprc","open")) or q.open)
        q.high=round(pick(data,("stck_hgpr","high")) or q.high)
        q.low=round(pick(data,("stck_lwpr","low")) or q.low)
        q.per=pick(data,("per","per_val")) or q.per
        q.pbr=pick(data,("pbr","pbr_val")) or q.pbr
        strength=pick(data,("cttr","volpower","execution_strength"))
        if strength:q.update_execution(strength)

    def _apply_us(self,code,data):
        q=self.q("US",code)
        name=pick_text(data,("kor_name","hts_kor_isnm","iem_nm"))
        if name:q.name=name
        sector=pick_text(data,("industry_name","industry_code"))
        if sector:q.sector=sector
        price=pick(data,("trdprc","ovrs_prpr","last","prc","price","close"))
        volume=pick(data,("acvol","acml_vol","tvol","volume","vol"))
        prev=pick(data,("hst_acvol",))
        if prev>0:q.prev_day_volume=prev
        if price:q.mark(price,volume)
        q.open=pick(data,("open_prc","ovrs_oprc","open")) or q.open
        q.high=pick(data,("high","ovrs_hgpr","high_prc")) or q.high
        q.low=pick(data,("low","ovrs_lwpr","low_prc")) or q.low
        self._update_us_fx_from_current(data)

    def _apply_investor(self,code,data):
        q=self.q("KR",code)
        f=pick(data,("frgn_ntby_qty","invest"))
        i=pick(data,("gigwan","orgn_ntby_qty"))
        person=pick(data,("person","prsn_ntby_qty"))
        program=pick(data,("program","prgm_ntby_qty"))
        objs=[o for o in walk(data) if isinstance(o,dict)]
        found_f=any(("frgn_ntby_qty" in o or "invest" in o) for o in objs)
        found_i=any(("gigwan" in o or "orgn_ntby_qty" in o) for o in objs)
        found_person=any(("person" in o or "prsn_ntby_qty" in o) for o in objs)
        found_program=any(("program" in o or "prgm_ntby_qty" in o) for o in objs)
        if found_f or found_i or found_program:
            q.update_flow(f if found_f else None,i if found_i else None,program if found_program else None)
        q.person_net=person if found_person else getattr(q,"person_net",0.0)

        # currentInvestor returns a recent investor series. Keep the latest 14
        # distinct trading days for smart-money accumulation analysis.
        rows=[];seen=set()
        for o in objs:
            if not any(k in o for k in ("frgn_ntby_qty","invest","gigwan","orgn_ntby_qty","person","prsn_ntby_qty")):
                continue
            d=normalize_date(o.get("bsop_date") or o.get("stck_bsop_date") or o.get("trade_date") or o.get("date") or o.get("xymd") or o.get("trd_dd"))
            if not d or d in seen:continue
            seen.add(d)
            rows.append({
                "date":d,
                "foreign":num(o.get("frgn_ntby_qty") if "frgn_ntby_qty" in o else o.get("invest")),
                "institution":num(o.get("gigwan") if "gigwan" in o else o.get("orgn_ntby_qty")),
                "person":num(o.get("person") if "person" in o else o.get("prsn_ntby_qty")),
                "program":num(o.get("program") if "program" in o else o.get("prgm_ntby_qty")),
            })
        if rows:
            rows.sort(key=lambda x:x["date"])
            q.investor_daily=deque(rows[-14:],maxlen=14)

    def _apply_program_message(self,msg):
        if not isinstance(msg,dict):return
        body=msg.get("body") if isinstance(msg.get("body"),dict) else msg
        code=str(body.get("code") or msg.get("header",{}).get("tr_key") or "").strip()
        if len(code)!=6:return
        net=num(body.get("sbidval"))
        netvol=num(body.get("sbidvol"))
        q=self.q("KR",code);q.program_net=net;q.program_net_volume=netvol;q.update_flow(program=net)
        self.program_realtime["connected"]=True;self.program_realtime["error"]="";self.program_realtime["updated_at"]=time.time()

    # ----- masters -----
    @staticmethod
    def _master_sector_name(row,code=""):
        if code in KR_THEME_OVERRIDES:return KR_THEME_OVERRIDES[code]
        k200=str(row.get("kospi200_apnt_cls_code") or row.get("eAccept") or "").strip().upper()
        if k200 in KOSPI200_SECTOR:return KOSPI200_SECTOR[k200]
        for key in ("bstp_medm_div_nm","bstp_larg_div_nm","industry_group_name","industry_name","sector_name","bstp_kor_isnm"):
            v=str(row.get(key) or "").strip()
            if v:return v
        if str(row.get("itgubun") or row.get("gIT") or "").strip()=="1":return "정보기술"
        up=str(row.get("bstp_medm_div_code") or row.get("sUpCodeM") or row.get("industry_group") or "").strip()
        return f"업종 {up}" if up and up not in ("000000","K00000","Q00000") else "기타"

    def _load_kr_master(self):
        try:
            from nhplug.instruments import load_master
            catalog={}
            for row in dataframe_rows(load_master("m_new_stock")):
                raw=str(row.get("shrn_iscd") or row.get("sCode") or row.get("code") or "")
                m=re.search(r"(\d{6})",raw)
                if not m:continue
                code=m.group(1)
                name=str(row.get("hts_kor_isnm") or row.get("name") or row.get("sKorName") or code).lstrip("*#").strip()
                sector=self._master_sector_name(row,code)
                self.kr_master_meta[code]={"code":code,"name":name,"sector":sector}
                catalog.setdefault(sector,[]).append({"code":code,"name":name})
            self.sector_catalog={k:sorted(v,key=lambda x:x["name"]) for k,v in catalog.items()}
            self._refresh_sector_scan_universe()
            for code in self.sector_scan_codes:
                meta=self.kr_master_meta.get(code,{})
                q=self.q("KR",code);q.name=meta.get("name",q.name or code);q.sector=meta.get("sector",q.sector)
        except Exception as exc:
            self.errors["KR"]=f"국내 종목마스터: {exc}"[:300]
            self.sector_scan_codes=list(self.fixed["KR"])
        self.code_lists["KR"]=list(dict.fromkeys(self.sector_scan_codes or self.fixed["KR"]))

    def _krx_openapi_get(self,path,bas_dd):
        if not self.krx_openapi_key:return {}
        url=f"https://data-dbg.krx.co.kr/svc/apis/{path}"
        r=requests.get(url,headers={"AUTH_KEY":self.krx_openapi_key,"User-Agent":"GY-Trading-OS/1.0"},params={"basDd":bas_dd},timeout=12)
        if r.status_code==401:raise RuntimeError("KRX OPEN API 인증키/활용승인 필요")
        r.raise_for_status();return r.json()

    def _recent_trade_dates(self,limit=45):
        d=datetime.now(KST);out=[]
        while len(out)<limit:
            if d.weekday()<5:out.append(d.strftime("%Y%m%d"))
            d-=timedelta(days=1)
        return out

    def _refresh_sector_scan_universe(self):
        # With a KRX OPEN API key, select the most liquid domestic shares once
        # from the latest available official daily market snapshot. This makes
        # the sector map materially broader without hammering NHPLUG for every
        # listed stock. Without a key, fall back to the explicit tracked list.
        if not self.krx_openapi_key:
            self.sector_scan_codes=list(self.fixed["KR"]);return
        for d in self._recent_trade_dates(8):
            rows=[]
            try:
                for path in ("sto/stk_bydd_trd","sto/ksq_bydd_trd"):
                    j=self._krx_openapi_get(path,d);rows.extend(j.get("OutBlock_1") or [])
            except Exception as exc:
                self.market_errors["sector_universe"]=str(exc)[:220];continue
            ranked=[]
            for r in rows:
                code=str(r.get("ISU_SRT_CD") or r.get("ISU_CD") or "").strip()
                m=re.search(r"(\d{6})",code)
                if not m:continue
                code=m.group(1)
                value=num(r.get("ACC_TRDVAL"));ranked.append((value,code))
            if ranked:
                ranked.sort(reverse=True)
                top=[c for _,c in ranked[:self.sector_scan_limit]]
                self.sector_scan_codes=list(dict.fromkeys(list(self.fixed["KR"])+top))
                self.sector_universe_asof=d;self.market_errors.pop("sector_universe",None);return
        self.sector_scan_codes=list(self.fixed["KR"])

    def sector_members(self,sector):
        members=list(self.sector_catalog.get(str(sector),[]))
        live=self.quotes["KR"]
        out=[]
        for m in members:
            q=live.get(m["code"]);row={"code":m["code"],"name":m["name"],"live":bool(q and q.price>0)}
            if q and q.price>0:
                row.update({"price":q.price,"change_pct":((q.price/q.open)-1)*100 if q.open else None,
                            "volume_ratio":(q.volume/q.prev_day_volume*100) if q.prev_day_volume>0 else None,
                            "foreign_net":q.foreign_net,"institution_net":q.institution_net,
                            "program_net":q.program_net,"person_net":getattr(q,"person_net",0.0),
                            "execution_strength":q.execution_strength})
            out.append(row)
        return out

    def _load_us_master(self):
        try:
            from nhplug.instruments import load_master
            wanted=set(self.fixed["US"])
            for row in dataframe_rows(load_master("m_gtsstock")):
                s=str(row.get("symbol") or row.get("sSymbol") or "").strip().upper()
                if s not in wanted:continue
                q=self.q("US",s);q.name=str(row.get("kor_name") or row.get("eng_name") or s).strip()
                industry=str(row.get("industry_group") or row.get("gIndustryReuter") or "").strip()
                q.sector=f"업종 {industry}" if industry else "미국주식"
        except Exception as exc:self.errors["US"]=f"해외 종목마스터: {exc}"[:300]
        self.code_lists["US"]=self.fixed["US"][:]

    # ----- scanners / flows / daily history -----
    def kr_scanner(self):
        self._load_kr_master();codes=self.code_lists["KR"] or self.fixed["KR"]
        from nhplug import call
        while not self._stop.is_set():
            code=codes[self.scan_index["KR"]%len(codes)];self.scan_index["KR"]=(self.scan_index["KR"]+1)%len(codes)
            err=""
            for market_cd in self._market_order():
                try:
                    data=call("/krstock/quote/v1/currentPrice",{"iem_cd":code,"market_cd":market_cd})
                    self._apply_kr(code,data)
                    if self.q("KR",code).price>0:
                        self.connected["KR"]=True;self.errors["KR"]="";break
                except Exception as exc:
                    err=f"{market_cd} {code}: {exc}"[:300]
                    if "429" in err:time.sleep(1.5);break
            if err and self.q("KR",code).price<=0:self.errors["KR"]=err
            self._stop.wait(.35)

    def investor_loop(self):
        from nhplug import call
        idx=0;codes=self.code_lists["KR"] or self.fixed["KR"]
        while not self._stop.is_set():
            code=codes[idx%len(codes)];idx+=1;err=""
            for market_cd in self._market_order():
                try:
                    data=call("/krstock/quote/v1/currentInvestor",{"market_cd":market_cd,"iem_cd":code,"array_cnt":"14"})
                    self._apply_investor(code,data);self.investor_updated_at=time.time();err="";break
                except Exception as exc:
                    err=str(exc)[:200]
                    if "429" in err:time.sleep(1.5);break
            self._stop.wait(.75)

    def program_loop(self):
        # One channel only. Reconnect with bounded exponential backoff so a
        # deployment/network flap does not create a tight reconnect storm.
        delay=1
        while not self._stop.is_set():
            try:
                from nhplug.realtime import subscribe
                subscribe(self.fixed["KR"],self._apply_program_message,tr_cd="mn",timeout=30)
                delay=1
                if not self.program_realtime["connected"]:
                    self.program_realtime["error"]="실시간 프로그램매매 수신 대기"
            except Exception as exc:
                self.program_realtime["connected"]=False
                self.program_realtime["error"]=str(exc)[:240]
                self._stop.wait(delay);delay=min(30,delay*2)

    def us_scanner(self):
        self._load_us_master();codes=self.code_lists["US"] or self.fixed["US"]
        from nhplug import call
        while not self._stop.is_set():
            code=codes[self.scan_index["US"]%len(codes)];self.scan_index["US"]=(self.scan_index["US"]+1)%len(codes)
            try:
                data=call("/gbstock/quote/v1/current",{"iem_cd":code});self._apply_us(code,data)
                if self.q("US",code).price>0:self.connected["US"]=True;self.errors["US"]=""
            except Exception as exc:
                self.errors["US"]=f"{code}: {exc}"[:300]
                if "429" in self.errors["US"]:time.sleep(1.5)
            self._stop.wait(.5)

    def _fetch_kr_daily(self,code,count=30):
        from nhplug import call
        last=None
        # Official NHPLUG sample explicitly sends array_cnt as a string.
        for market_cd in self._market_order():
            try:
                data=call("/krstock/quote/v1/currentDaily",{
                    "market_cd":market_cd,"iem_cd":code,"array_cnt":str(max(1,int(count)))
                })
                bars=parse_daily_rows(data,"KR")
                if bars:return bars[-count:]
            except Exception as exc:last=exc
        if last:raise last
        return []

    def _fetch_us_daily(self,code,count=30):
        from nhplug import call
        end=datetime.now(KST).strftime("%Y%m%d")
        # Official overseas stock period API: gubun=3 is daily and count is
        # a 4-character string field.
        data=call("/gbstock/quote/v1/period",{
            "iem_cd":code,"end_dt":end,"count":f"{max(1,int(count)):04d}","maxavg":"005",
            "gubun":"3","xtick":"0001","today_cls":"0","market_cls":"0",
        })
        return parse_daily_rows(data,"US")[-count:]

    def ensure_daily_bars(self,market,code,count=30,force=False):
        market="US" if str(market).upper()=="US" else "KR"
        q=self.q(market,code);count=max(1,int(count));key=f"{market}:{str(code).upper()}"
        if not force and len(q.daily_bars)>=count:
            return list(q.daily_bars)[-count:]
        now=time.time();last=self.daily_fetch_attempt_at.get(key,0.0)
        # Stock detail refreshes every five seconds; do not turn that into a
        # historical-API request storm if the upstream returns fewer bars.
        if not force and now-last<60:
            return list(q.daily_bars)[-count:]
        self.daily_fetch_attempt_at[key]=now
        bars=self._fetch_kr_daily(code,count) if market=="KR" else self._fetch_us_daily(code,count)
        if bars:q.set_daily_bars(bars)
        return list(q.daily_bars)[-count:]

    def history_loop(self):
        idx={"KR":0,"US":0}
        while not self._stop.is_set():
            for market in ("KR","US"):
                codes=(self.code_lists[market] or self.fixed[market])
                code=codes[idx[market]%len(codes)];idx[market]+=1
                try:
                    bars=self._fetch_kr_daily(code,30) if market=="KR" else self._fetch_us_daily(code,30)
                    if bars:self.q(market,code).set_daily_bars(bars)
                    self.history_updated_at=time.time()
                except Exception:
                    pass
                self._stop.wait(1.0)
            # each symbol refreshes every roughly 40 sec, gentle enough for cache warmup.

    def bars(self,market,code,timeframe="1m"):
        q=self.q(market,code);tf=str(timeframe).lower()
        if tf in ("d","1d","day","일봉"):
            return [{"time":b["date"],"open":b["open"],"high":b["high"],"low":b["low"],
                     "close":b["close"],"volume":b["volume"]} for b in q.daily_bars][-120:]
        mins={"1m":1,"3m":3,"5m":5,"20m":20}.get(tf,1)
        return aggregate_ticks(list(q.tick_history),mins)

    # ----- market index helpers -----
    @staticmethod
    def _market_item(label,value,change,change_pct,status,source="",series=None,asof=""):
        return {"label":label,"value":value,"change":change,"change_pct":change_pct,"status":status,
                "source":source,"series":list(series or []),"asof":asof}

    def _krx_home_text(self):
        headers={"User-Agent":"Mozilla/5.0 Chrome/131 Safari/537.36","Accept-Language":"en-US,en;q=0.9,ko;q=0.8"}
        last=None
        for url in ("https://global.krx.co.kr/","https://global.krx.co.kr/cn/main/main.jsp"):
            try:
                r=requests.get(url,headers=headers,timeout=8);r.raise_for_status()
                text=html_lib.unescape(re.sub(r"<[^>]+>"," ",r.text));text=re.sub(r"\s+"," ",text).strip()
                if "KOSPI" in text and "KOSDAQ" in text:return text
            except Exception as exc:last=exc
        raise RuntimeError(f"KRX Global 홈페이지 조회 실패: {last}")

    @staticmethod
    def _parse_krx_home_index(text,label):
        m=re.search(rf"\b{re.escape(label)}\b\s*([\d,]+(?:\.\d+)?)\s*([▲▼]?)\s*([\d,]+(?:\.\d+)?)?\s*(?:\(\s*([\d.]+)\s*\))?",text,re.I)
        if not m:raise RuntimeError(f"{label} 값 파싱 실패")
        v=num(m.group(1));sign=m.group(2) or "";ch=num(m.group(3));pct=num(m.group(4))
        if sign=="▼":ch=-abs(ch);pct=-abs(pct)
        elif sign=="▲":ch=abs(ch);pct=abs(pct)
        if v<=0:raise RuntimeError(f"{label} 값이 0 이하")
        return v,ch,pct

    def _krx_status(self):
        now=datetime.now(KST);m=now.hour*60+now.minute
        return "장중 공식값" if now.weekday()<5 and 540<=m<=930 else "최근 종가"

    def _update_krx_series(self,key,value,change):
        s=self.krx_series[key]
        if not s:
            prev=value-change if change else value
            if prev>0:s.append(round(prev,4))
        if not s or abs(s[-1]-value)>1e-9:s.append(round(value,4))
        self.krx_series[key]=s[-60:]
        return list(self.krx_series[key])

    def _krx_warm_session(self,force=False):
        now=time.time()
        if not force and now-self.krx_http_warmed_at<1800:return
        ua="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36"
        try:
            self.krx_http.get("https://data.krx.co.kr/contents/MDC/MDI/outerLoader/index.cmd",headers={"User-Agent":ua},timeout=10)
            self.krx_http_warmed_at=now
        except Exception:
            pass

    def _krx_login_if_configured(self):
        if self.krx_logged_in:return True
        login_id=os.getenv("KRX_ID","").strip();login_pw=os.getenv("KRX_PW","").strip()
        if not login_id or not login_pw:return False
        ua="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36"
        page="https://data.krx.co.kr/contents/MDC/COMS/client/MDCCOMS001.cmd"
        jsp="https://data.krx.co.kr/contents/MDC/COMS/client/view/login.jsp?site=mdc"
        url="https://data.krx.co.kr/contents/MDC/COMS/client/MDCCOMS001D1.cmd"
        try:
            self.krx_http.get(page,headers={"User-Agent":ua},timeout=10)
            self.krx_http.get(jsp,headers={"User-Agent":ua,"Referer":page},timeout=10)
            payload={"mbrNm":"","telNo":"","di":"","certType":"","mbrId":login_id,"pw":login_pw}
            r=self.krx_http.post(url,data=payload,headers={"User-Agent":ua,"Referer":jsp},timeout=10);j=r.json()
            if j.get("_error_code")=="CD011":
                payload["skipDup"]="Y";j=self.krx_http.post(url,data=payload,headers={"User-Agent":ua,"Referer":jsp},timeout=10).json()
            self.krx_logged_in=j.get("_error_code")=="CD001"
            return self.krx_logged_in
        except Exception:
            return False

    def _krx_post(self,payload):
        self._krx_warm_session()
        headers={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36",
                 "Referer":"https://data.krx.co.kr/contents/MDC/MDI/outerLoader/index.cmd",
                 "X-Requested-With":"XMLHttpRequest"}
        url="https://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd"
        r=self.krx_http.post(url,data=payload,headers=headers,timeout=12);r.raise_for_status()
        try:j=r.json()
        except Exception:raise RuntimeError("KRX JSON 응답 아님")
        # 2026 KRX session policy can require login for some data calls. If
        # credentials are configured, transparently log in and retry once.
        if (j.get("_error_code") or j.get("_error_message")) and self._krx_login_if_configured():
            r=self.krx_http.post(url,data=payload,headers=headers,timeout=12);r.raise_for_status();j=r.json()
        return j

    @staticmethod
    def _parse_krx_index_rows(rows):
        out=[]
        for x in rows or []:
            if not isinstance(x,dict):continue
            d=normalize_date(x.get("TRD_DD"));c=num(x.get("CLSPRC_IDX"))
            if not d or c<=0:continue
            out.append({"date":d,"open":num(x.get("OPNPRC_IDX")) or c,"high":num(x.get("HGPRC_IDX")) or c,
                        "low":num(x.get("LWPRC_IDX")) or c,"close":c,"volume":num(x.get("ACC_TRDVOL"))})
        out.sort(key=lambda x:x["date"]);return out

    def _fetch_krx_index_daily_openapi(self,key,count=40):
        if not self.krx_openapi_key:return []
        path={"kospi":"idx/kospi_dd_trd","kosdaq":"idx/kosdaq_dd_trd"}.get(key)
        exact_name={"kospi":"코스피","kosdaq":"코스닥"}.get(key)
        if not path:return []
        got=[]
        for d in self._recent_trade_dates(max(45,count+12)):
            try:
                j=self._krx_openapi_get(path,d)
            except Exception as exc:
                self.market_daily_error[key]=str(exc)[:220];break
            rows=j.get("OutBlock_1") or []
            chosen=None
            for r in rows:
                if str(r.get("IDX_NM") or "").strip()==exact_name:
                    chosen=r;break
            if not chosen and rows:
                chosen=rows[0]
            if chosen:
                c=num(chosen.get("CLSPRC_IDX"))
                if c>0:
                    got.append({"date":normalize_date(chosen.get("BAS_DD") or d),
                                "open":num(chosen.get("OPNPRC_IDX")) or c,
                                "high":num(chosen.get("HGPRC_IDX")) or c,
                                "low":num(chosen.get("LWPRC_IDX")) or c,
                                "close":c,"volume":num(chosen.get("ACC_TRDVOL"))})
            if len(got)>=count:break
        got.sort(key=lambda x:x["date"])
        if got:self.market_daily_error[key]=""
        return got[-count:]

    def _fetch_krx_index_daily(self,key,count=40):
        official=self._fetch_krx_index_daily_openapi(key,count)
        if official:return official
        code={"kospi":("1","001","02","코스피"),"kosdaq":("2","001","03","코스닥")}.get(key)
        if not code:return []
        end=datetime.now(KST).strftime("%Y%m%d");start=(datetime.now(KST)-timedelta(days=100)).strftime("%Y%m%d")
        payload={"bld":"dbms/MDC/STAT/standard/MDCSTAT00301","indIdx":code[0],"indIdx2":code[1],"strtDd":start,"endDd":end}
        j=self._krx_post(payload);rows=j.get("output") or j.get("OutBlock_1") or j.get("output1") or []
        out=self._parse_krx_index_rows(rows)
        if out:return out[-count:]
        # Some KRX sessions intermittently return an empty range response.
        # Fallback stays on KRX official data: request daily all-index snapshots
        # and extract only the exact KOSPI/KOSDAQ row. No synthetic candles.
        got=[];d=datetime.now(KST);tries=0
        while len(got)<min(count,12) and tries<16:
            tries+=1
            if d.weekday()<5:
                q={"bld":"dbms/MDC/STAT/standard/MDCSTAT00101","idxIndMidclssCd":code[2],"trdDd":d.strftime("%Y%m%d")}
                try:
                    jj=self._krx_post(q);rr=jj.get("output") or []
                    exact=[]
                    for x in rr:
                        if not isinstance(x,dict):continue
                        nm=str(x.get("IDX_NM") or x.get("IDX_IND_NM") or "").strip()
                        if nm==code[3]:
                            y=dict(x);y["TRD_DD"]=d.strftime("%Y%m%d");exact.append(y);break
                    got.extend(self._parse_krx_index_rows(exact))
                except Exception:
                    pass
            d-=timedelta(days=1)
        got.sort(key=lambda x:x["date"]);return got[-count:]

    def _refresh_krx_daily(self,force=False):
        now=time.time()
        for key in ("kospi","kosdaq"):
            if not force and self.market_daily_bars[key] and now-self.market_daily_updated_at[key]<900:continue
            try:
                bars=self._fetch_krx_index_daily(key,40)
                if bars:
                    self._set_market_daily_bars(key,bars);self.market_daily_error[key]=""
                elif not self.market_daily_error.get(key):
                    self.market_daily_error[key]="KRX 일봉 응답이 비어 있음"
            except Exception as exc:
                self.market_daily_error[key]=str(exc)[:220]

    def refresh_market_daily(self,key,force=False):
        key=str(key).lower()
        if key in ("kospi","kosdaq"):
            self._refresh_krx_daily(force=force)
        return self.market_bars(key,"1d")

    def entry_data_status(self,market,code,now_ts=None):
        market="US" if str(market).upper()=="US" else "KR";now_ts=float(now_ts or time.time())
        q=self.quotes_for(market).get(str(code).upper())
        if not q or q.price<=0:return False,"현재가 미수신"
        if now_ts-float(q.updated_at or 0)>25:return False,"현재가 25초 이상 지연"
        if market=="KR":
            fh=list(q.flow_history)
            if not fh or now_ts-float(fh[-1][0])>90:return False,"투자자 수급 90초 이상 지연"
            eh=list(q.execution_history)
            if not eh or now_ts-float(eh[-1][0])>30:return False,"체결강도 30초 이상 지연"
            pr=self.program_realtime
            if pr.get("connected") and now_ts-float(pr.get("updated_at") or 0)>90:return False,"프로그램 실시간 90초 이상 지연"
        return True,"정상"

    def _read_krx_indices(self):
        text=self._krx_home_text();status=self._krx_status();out={}
        for key,raw,label in (("kospi","KOSPI","코스피"),("kosdaq","KOSDAQ","코스닥")):
            v,ch,pct=self._parse_krx_home_index(text,raw)
            out[key]=self._market_item(label,v,ch,pct,status,"KRX 공식",self._update_krx_series(key,v,ch))
        return out

    def krx_loop(self):
        while not self._stop.is_set():
            try:
                for key,item in self._read_krx_indices().items():self._record_market_item(key,item)
                try:self._refresh_krx_daily()
                except Exception as exc:self.market_errors["krx_daily"]=str(exc)[:500]
                self.market_errors.pop("krx_indices",None)
            except Exception as exc:self.market_errors["krx_indices"]=str(exc)[:500]
            self.market_updated_at=time.time();self._stop.wait(60)

    def _symbol_candidates(self,key):
        configured=self.index_symbols.get(key,"")
        defaults={"sp500":["SPX","N@SPX"],"nasdaq":["COMP","IXIC","NDX","N@IXIC"],"sox":["SOX","PHLXSOX","N@SOX"]}
        out=[configured] if configured else []
        for x in defaults.get(key,[]):
            if x not in out:out.append(x)
        return out

    def _read_symbol_period_one(self,key,symbol,label,status="종가 기준"):
        from nhplug import call
        today=datetime.now(KST).strftime("%Y%m%d")
        # Official schema: array_cnt is a 4-character string. Using an int
        # produces IGW40011 on this endpoint. Keep 30 trading-day closes so
        # weekends/holidays still show a meaningful official curve.
        data=call("/gbstock/quote/v1/symbolIndexFxPeriod",{
            "iem_cd":symbol,"end_dt":today,"array_cnt":"0030","maxavg":"005",
            "gubun":"1","xtick":"001","today_cls":"0","scale_change":"0"
        })
        value=pick(data,("ovrs_prpr","close_prc","last","close","prpr"))
        sign=pick_text(data,("prdy_vrss_sign","sign"))
        change=signed_value(pick(data,("prdy_vrss","change")),sign)
        pct=signed_value(pick(data,("prdy_ctrt","change_rate")),sign)
        rows=first_list(data,("Output_1","output_1"));dated=[];daily=[]
        for r in rows:
            if not isinstance(r,dict):continue
            d=normalize_date(r.get("bsop_date") or r.get("xymd") or r.get("date"))
            v=num(r.get("ovrs_prpr") or r.get("close_prc") or r.get("close") or r.get("last"))
            if d and v>0:
                dated.append((d,v));daily.append({"date":d,
                    "open":num(r.get("ovrs_oprc") or r.get("open_prc") or r.get("open")) or v,
                    "high":num(r.get("ovrs_hgpr") or r.get("high") or r.get("high_prc")) or v,
                    "low":num(r.get("ovrs_lwpr") or r.get("low") or r.get("low_prc")) or v,
                    "close":v,"volume":num(r.get("vol") or r.get("acml_vol") or r.get("volume"))})
        self._set_market_daily_bars(key,daily)
        # The server can return newest-first; sort explicitly.
        dated=sorted(dict(dated).items())[-30:]
        series=[v for _,v in dated];asof=dated[-1][0] if dated else ""
        if not value and series:value=series[-1]
        if value<=0:raise RuntimeError(f"{label} value missing for {symbol}")
        if not series:series=[value-change if change and value-change>0 else value,value]
        elif abs(series[-1]-value)>1e-9:series=(series+[value])[-30:]
        asof=asof or today
        return self._market_item(label,value,change,pct,f"공식 30거래일 추이 · {asof[:4]}-{asof[4:6]}-{asof[6:]}","NHPLUG",series[-30:],asof)

    def _read_symbol_period(self,key,label,status="종가 기준"):
        errs=[]
        for s in self._symbol_candidates(key):
            try:
                x=self._read_symbol_period_one(key,s,label,status);self.index_symbols[key]=s;return x
            except Exception as exc:errs.append(f"{s}: {exc}")
        raise RuntimeError(" | ".join(errs)[-900:])

    def _read_sox_nasdaq(self):
        url="https://indexes.nasdaq.com/Index/Overview/SOX";headers={"User-Agent":"Mozilla/5.0 Chrome/131 Safari/537.36"}
        r=requests.get(url,headers=headers,timeout=10);r.raise_for_status()
        text=html_lib.unescape(re.sub(r"<[^>]+>"," ",r.text));text=re.sub(r"\s+"," ",text)
        m=re.search(r"DATA\s+AS\s+OF\s+(\d{1,2}/\d{1,2}/\d{4})\s+([\d,]+(?:\.\d+)?)\s+([+-]?[\d,]+(?:\.\d+)?)\s+([+-]?[\d.]+)%",text,re.I)
        if not m:raise RuntimeError("Nasdaq SOX 공식값 파싱 실패")
        d,rv,rc,rp=m.groups();v=num(rv);ch=num(rc);pct=num(rp)
        if v<=0:raise RuntimeError("Nasdaq SOX 값이 0 이하")
        asof=datetime.strptime(d,"%m/%d/%Y").strftime("%Y%m%d");prev=v-ch
        existing=self.market.get("sox",{}).get("series",[])
        if len(existing)>=3:
            series=list(existing)[-29:]
            if not series or abs(series[-1]-v)>1e-9:series.append(v)
        else:
            series=[prev,v] if prev>0 else [v]
        return self._market_item("필라델피아 반도체지수",v,ch,pct,f"공식값 · {asof[:4]}-{asof[4:6]}-{asof[6:]}",
                                 "Nasdaq 공식",series[-30:],asof)

    def _discover_futures(self, force=False):
        """Resolve current futures symbols from NHPLUG masters.

        Expiring futures can stop returning quotes. When no explicit environment
        override is configured, force=True lets the feed re-scan the official
        masters and move to the current contract automatically.
        """
        try:
            from nhplug.instruments import load_master

            env_kr=os.getenv("NH_KOSPI_NIGHT_SYMBOL","").strip().upper()
            env_us=os.getenv("NH_NASDAQ_FUTURE_SYMBOL","").strip().upper()
            env_us_ex=os.getenv("NH_NASDAQ_FUTURE_EXNM","FCME").strip().upper() or "FCME"

            if env_kr:
                self.future_symbols["kospi_night"]=env_kr
            elif force:
                self.future_symbols["kospi_night"]=""

            if env_us:
                self.future_symbols["nasdaq_future"]=env_us
                self.future_symbols["nasdaq_future_exnm"]=env_us_ex
            elif force:
                self.future_symbols["nasdaq_future"]=""

            if not self.future_symbols["kospi_night"]:
                rows=dataframe_rows(load_master("m_future"))
                exact=[];fallback=[]
                for row in rows:
                    code=str(
                        row.get("code") or row.get("sCode") or row.get("shrn_iscd")
                        or row.get("isym") or row.get("symbol") or ""
                    ).strip().upper()
                    name=str(
                        row.get("name") or row.get("sName") or row.get("hts_kor_isnm")
                        or row.get("kor_name") or row.get("enam") or row.get("EngName") or ""
                    ).strip()
                    if not code.startswith("KA"):
                        continue
                    fallback.append(code)
                    normalized=re.sub(r"\s+","",name).upper()
                    if "KOSPI200" in normalized or "코스피200" in normalized:
                        exact.append(code)
                candidates=exact or fallback
                if candidates:
                    # Official master ordering normally puts the active/front
                    # contract first. Keep that order instead of lexical sorting.
                    self.future_symbols["kospi_night"]=candidates[0]

            if not self.future_symbols["nasdaq_future"]:
                cand=[]
                for idx,row in enumerate(dataframe_rows(load_master("fucode_h"))):
                    s=str(
                        row.get("isym") or row.get("InnerSymbol") or row.get("symb")
                        or row.get("symbol") or row.get("code") or ""
                    ).strip().upper()
                    name=str(
                        row.get("enam") or row.get("EngName") or row.get("name")
                        or row.get("sName") or ""
                    ).strip()
                    if not s or "NASDAQ" not in name.upper():
                        continue
                    lead=str(row.get("ledm") or row.get("lead") or "").strip()
                    ex=str(row.get("exnm") or row.get("exchange") or env_us_ex or "FCME").strip().upper() or "FCME"
                    cand.append((1 if lead=="1" else 0,-idx,s,ex))
                if cand:
                    cand.sort(reverse=True)
                    _,_,s,e=cand[0]
                    self.future_symbols["nasdaq_future"]=s
                    self.future_symbols["nasdaq_future_exnm"]=e

            if not self.future_symbols["kospi_night"]:
                raise RuntimeError("코스피 야간선물 종목코드 자동탐색 실패")
            if not self.future_symbols["nasdaq_future"]:
                raise RuntimeError("NASDAQ 선물 선도월물 자동탐색 실패")

            self.market_errors.pop("future_master",None)
        except Exception as exc:
            self.market_errors["future_master"]=str(exc)[:300]

    def _refresh_kospi_night_history(self,force=False):
        now=time.time()
        if not force and self.future_history["kospi_night"] and now-self.future_history_updated_at["kospi_night"]<900:
            return list(self.future_history["kospi_night"])
        from nhplug import call
        s=self.future_symbols.get("kospi_night","")
        if not s:return list(self.future_history["kospi_night"])
        data=call("/krfuture/quote/v1/nightPeriod",{
            "iem_cd":s,"mrkt_div_cls_code":"F","edate":datetime.now(KST).strftime("%Y%m%d"),
            "array_cnt":"0030","maxavg":"005","gubun":"1","xtick":"001",
            "today_cls_code":"0","out1_scale_change":"0","out2_scale_change":"0"
        })
        rows=first_list(data,("Output_1","output_1"));dated=[];daily=[]
        for r in rows:
            if not isinstance(r,dict):continue
            d=normalize_date(r.get("bsop_date") or r.get("date"));v=num(r.get("prpr") or r.get("clpr") or r.get("close"))
            if d and v>0:
                dated.append((d,v));daily.append({"date":d,"open":num(r.get("oprc")) or v,"high":num(r.get("hgpr")) or v,
                    "low":num(r.get("lwpr")) or v,"close":v,"volume":num(r.get("vol"))})
        dated=sorted(dict(dated).items())[-30:]
        if dated:
            self.future_history["kospi_night"]=[v for _,v in dated];self._set_market_daily_bars("kospi_night",daily)
            self.future_history_updated_at["kospi_night"]=now
        return list(self.future_history["kospi_night"])

    def _refresh_nasdaq_future_history(self,force=False):
        now=time.time()
        if not force and self.future_history["nasdaq_future"] and now-self.future_history_updated_at["nasdaq_future"]<900:
            return list(self.future_history["nasdaq_future"])
        from nhplug import call
        s=self.future_symbols.get("nasdaq_future","")
        e=self.future_symbols.get("nasdaq_future_exnm","FCME") or "FCME"
        if not s:return list(self.future_history["nasdaq_future"])
        start=(datetime.now(KST)-timedelta(days=60)).strftime("%Y%m%d")
        data=call("/gbfuture/quote/v1/executionTrendDaily",{
            "exnm":e,"iem_cd":s,"ssymd":start,"quotyn":"Y","req_cnt":"0030"
        })
        rows=first_list(data,("Output_0","output_0"));dated=[];daily=[]
        for r in rows:
            if not isinstance(r,dict):continue
            d=normalize_date(r.get("tymd") or r.get("bsop_date") or r.get("date"));v=num(r.get("clos") or r.get("last") or r.get("close"))
            if d and v>0:
                dated.append((d,v));daily.append({"date":d,"open":num(r.get("open")) or v,"high":num(r.get("high")) or v,
                    "low":num(r.get("low")) or v,"close":v,"volume":num(r.get("tvol"))})
        dated=sorted(dict(dated).items())[-30:]
        if dated:
            self.future_history["nasdaq_future"]=[v for _,v in dated];self._set_market_daily_bars("nasdaq_future",daily)
            self.future_history_updated_at["nasdaq_future"]=now
        return list(self.future_history["nasdaq_future"])

    def _read_kospi_night(self):
        from nhplug import call
        s=self.future_symbols.get("kospi_night","")
        if not s:
            raise RuntimeError("코스피 야간선물 종목코드 자동탐색 실패")
        d=call("/krfuture/quote/v1/night",{"iem_cd":s})
        v=pick(d,("prpr","stck_prpr","last","close","current_prc","now_pr"))
        sign=pick_text(d,("sign","prdy_vrss_sign"))
        if v<=0:
            raise RuntimeError(f"{s} 야간선물 현재가 없음")
        ch=signed_value(pick(d,("vrss","prdy_vrss","diff","change")),sign)
        pct=signed_value(pick(d,("ctrt","prdy_ctrt","rate","change_rate")),sign)
        try:series=self._refresh_kospi_night_history()
        except Exception:series=list(self.future_history.get("kospi_night",[]))
        if series:
            if abs(series[-1]-v)>1e-9:series=(series+[v])[-30:]
        else:
            old=self.market.get("kospi_night",{}).get("series",[])
            series=(old+[v])[-30:]
        return self._market_item(
            "코스피 야간선물",v,ch,pct,"공식 30거래일 추이 · 현재가 15초 갱신","NHPLUG",
            series[-30:],datetime.now(KST).strftime("%Y%m%d")
        )

    def _read_nasdaq_future(self):
        from nhplug import call
        s=self.future_symbols.get("nasdaq_future","")
        e=self.future_symbols.get("nasdaq_future_exnm","FCME") or "FCME"
        if not s:
            raise RuntimeError("NASDAQ 선물 선도월물 자동탐색 실패")
        d=call("/gbfuture/quote/v1/current",{"exnm":e,"iem_cd":s})
        v=pick(d,("last","ovrs_prpr","close_prc","close","prpr","price"))
        sign=pick_text(d,("sign","prdy_vrss_sign"))
        if v<=0:
            raise RuntimeError(f"{s} 나스닥 선물 현재가 없음")
        ch=signed_value(pick(d,("diff","prdy_vrss","change")),sign)
        pct=signed_value(pick(d,("rate","prdy_ctrt","change_rate")),sign)
        try:series=self._refresh_nasdaq_future_history()
        except Exception:series=list(self.future_history.get("nasdaq_future",[]))
        if series:
            if abs(series[-1]-v)>1e-9:series=(series+[v])[-30:]
        else:
            old=self.market.get("nasdaq_future",{}).get("series",[])
            series=(old+[v])[-30:]
        return self._market_item(
            "나스닥 선물",v,ch,pct,"공식 30거래일 추이 · 현재가 15초 갱신","NHPLUG",
            series[-30:],datetime.now(KST).strftime("%Y%m%d")
        )

    def reference_loop(self):
        while not self._stop.is_set():
            for key,label in (("sp500","S&P500"),("nasdaq","나스닥")):
                try:self._record_market_item(key,self._read_symbol_period(key,label));self.market_errors.pop(key,None)
                except Exception as exc:self.market_errors[key]=str(exc)[:500]
            try:
                try:item=self._read_symbol_period("sox","필라델피아 반도체지수")
                except Exception:item=self._read_sox_nasdaq()
                self._record_market_item("sox",item);self.market_errors.pop("sox",None)
            except Exception as exc:self.market_errors["sox"]=str(exc)[:500]
            self.market_updated_at=time.time();self._stop.wait(60)

    def futures_loop(self):
        self._discover_futures()
        last_discovery=time.time()
        while not self._stop.is_set():
            if time.time()-last_discovery>=300:
                self._discover_futures(force=True)
                last_discovery=time.time()
            for key,fn in (("kospi_night",self._read_kospi_night),("nasdaq_future",self._read_nasdaq_future)):
                try:
                    self._record_market_item(key,fn())
                    self.market_errors.pop(key,None)
                except Exception as exc:
                    self.market_errors[key]=str(exc)[:300]
                    # Futures expire. If an env override was not pinned, refresh
                    # the official master immediately and retry on the next loop.
                    if key=="kospi_night" and not os.getenv("NH_KOSPI_NIGHT_SYMBOL","").strip():
                        self.future_symbols["kospi_night"]=""
                    if key=="nasdaq_future" and not os.getenv("NH_NASDAQ_FUTURE_SYMBOL","").strip():
                        self.future_symbols["nasdaq_future"]=""
                    self._discover_futures(force=False)
                    last_discovery=time.time()
            self.market_updated_at=time.time()
            self._stop.wait(15)

    def _pending(self,key,label,source="NHPLUG"):
        err=self.market_errors.get(key);status=f"수신 오류 · {err[:100]}" if err else "수신 대기"
        out=self._market_item(label,None,None,None,status,source,[]);out["key"]=key;return out

    def _current_or_pending(self,key,label,source="NHPLUG"):
        item=self.market.get(key);err=self.market_errors.get(key)
        if not item:return self._pending(key,label,source)
        out=dict(item);out["key"]=key
        if err:out["status"]=f"마지막 수신값 · 현재 오류: {err[:90]}"
        return out

    def market_state(self,market):
        if str(market).upper()=="KR":
            return [
                self._current_or_pending("kospi","코스피","KRX 공식"),
                self._current_or_pending("kosdaq","코스닥","KRX 공식"),
                self._current_or_pending("kospi_night","코스피 야간선물"),
                self._current_or_pending("nasdaq_future","나스닥 선물"),
                self._current_or_pending("sox","필라델피아 반도체지수"),
            ]
        return [
            self._current_or_pending("sp500","S&P500"),
            self._current_or_pending("nasdaq","나스닥"),
            self._current_or_pending("nasdaq_future","나스닥 선물"),
            self._current_or_pending("sox","필라델피아 반도체지수"),
        ]

    def health(self):
        return {"nh_realtime":self.connected_any(),"realtime":dict(self.connected),"errors":dict(self.errors),
                "kr_tracked":len(self.code_lists["KR"] or self.fixed["KR"]),"kr_priced":sum(q.price>0 for q in self.quotes["KR"].values()),
                "us_tracked":len(self.fixed["US"]),"us_priced":sum(q.price>0 for q in self.quotes["US"].values()),
                "market_updated_at":self.market_updated_at,"market_errors":dict(self.market_errors),
                "usdkrw":self.usdkrw,"usdkrw_asof":self.usdkrw_asof,"usdkrw_tradeable":self.usdkrw_tradeable,
                "usdkrw_source":self.usdkrw_source,"program_realtime":dict(self.program_realtime),
                "investor_updated_at":self.investor_updated_at,"history_updated_at":self.history_updated_at,
                "future_symbols":dict(self.future_symbols),"market_daily_error":dict(self.market_daily_error),
                "krx_openapi_configured":bool(self.krx_openapi_key),"sector_catalog_count":sum(len(v) for v in self.sector_catalog.values()),
                "sector_scan_count":len(self.code_lists["KR"] or self.fixed["KR"]),"sector_universe_asof":self.sector_universe_asof}

    def start(self):
        for target in (self.kr_scanner,self.investor_loop,self.program_loop,self.us_scanner,
                       self.history_loop,self.krx_loop,self.reference_loop,self.futures_loop):
            threading.Thread(target=target,daemon=True).start()
