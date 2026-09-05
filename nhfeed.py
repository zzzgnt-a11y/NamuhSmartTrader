from __future__ import annotations
import html as html_lib
import os
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable
import requests

from engine import Quote

KST=timezone(timedelta(hours=9))
KR_DEFAULT_CODES=["005930","000660","035420","035720","068270","012450","267260","042700","005380","000270","105560","055550","086790","028260","207940"]
US_DEFAULT_CODES=["AAPL","MSFT","NVDA","AMZN","META","GOOGL","TSLA","AVGO","AMD","NFLX","COST","PLTR","JPM","BAC","WMT","LLY","UNH","XOM","CVX","ORCL","CRM","ADBE","QCOM","MU","INTC","ARM","TSM"]

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
    rows=first_list(data,("Output_0","output_0","Output_1","output_1","output"))
    out=[]
    for r in rows:
        if not isinstance(r,dict):continue
        date=normalize_date(r.get("bsop_date") or r.get("xymd") or r.get("date") or r.get("trade_date"))
        close=num(r.get("stck_clpr") or r.get("ovrs_prpr") or r.get("close_prc") or r.get("close") or r.get("trdprc"))
        if not date or close<=0:continue
        out.append({
            "date":date,
            "open":num(r.get("stck_oprc") or r.get("open_prc") or r.get("open")) or close,
            "high":num(r.get("stck_hgpr") or r.get("high") or r.get("high_prc")) or close,
            "low":num(r.get("stck_lwpr") or r.get("low") or r.get("low_prc")) or close,
            "close":close,
            "volume":num(r.get("acml_vol") or r.get("acvol") or r.get("volume") or r.get("vol")),
        })
    # Some APIs return newest first.
    out.sort(key=lambda x:x["date"])
    return out

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
        f=pick(data,("frgn_ntby_qty",))
        i=pick(data,("gigwan","orgn_ntby_qty"))
        # Zero is a valid neutral value; update whenever endpoint returned the fields.
        found_f=any("frgn_ntby_qty" in o for o in walk(data) if isinstance(o,dict))
        found_i=any(("gigwan" in o or "orgn_ntby_qty" in o) for o in walk(data) if isinstance(o,dict))
        if found_f or found_i:q.update_flow(f if found_f else None,i if found_i else None,None)

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
    def _load_kr_master(self):
        try:
            from nhplug.instruments import load_master
            wanted=set(self.fixed["KR"])
            for row in dataframe_rows(load_master("m_new_stock")):
                raw=str(row.get("shrn_iscd") or row.get("sCode") or row.get("code") or "")
                m=re.search(r"(\d{6})",raw)
                if not m or m.group(1) not in wanted:continue
                code=m.group(1);q=self.q("KR",code)
                q.name=str(row.get("hts_kor_isnm") or row.get("name") or row.get("sKorName") or code).lstrip("*#").strip()
                q.sector=str(row.get("bstp_medm_div_code") or row.get("industry_group") or "").strip()
        except Exception as exc:self.errors["KR"]=f"국내 종목마스터: {exc}"[:300]
        self.code_lists["KR"]=self.fixed["KR"][:]

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
        idx=0;codes=self.fixed["KR"]
        while not self._stop.is_set():
            code=codes[idx%len(codes)];idx+=1;err=""
            for market_cd in self._market_order():
                try:
                    data=call("/krstock/quote/v1/currentInvestor",{"market_cd":market_cd,"iem_cd":code,"array_cnt":10})
                    self._apply_investor(code,data);self.investor_updated_at=time.time();err="";break
                except Exception as exc:
                    err=str(exc)[:200]
                    if "429" in err:time.sleep(1.5);break
            self._stop.wait(.75)

    def program_loop(self):
        # One channel only. SDK splits 15 keys across exactly two sessions, respecting NHPLUG limits.
        while not self._stop.is_set():
            try:
                from nhplug.realtime import subscribe
                subscribe(self.fixed["KR"],self._apply_program_message,tr_cd="mn",timeout=30)
                if not self.program_realtime["connected"]:
                    self.program_realtime["error"]="실시간 프로그램매매 수신 대기"
            except Exception as exc:
                self.program_realtime["error"]=str(exc)[:240]
                self._stop.wait(2)

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

    def _fetch_kr_daily(self,code):
        from nhplug import call
        last=None
        for market_cd in self._market_order():
            try:
                data=call("/krstock/quote/v1/currentDaily",{"market_cd":market_cd,"iem_cd":code,"array_cnt":12})
                bars=parse_daily_rows(data,"KR")
                if bars:return bars
            except Exception as exc:last=exc
        if last:raise last
        return []

    def _fetch_us_daily(self,code):
        from nhplug import call
        end=datetime.now(KST).strftime("%Y%m%d")
        # Official overseas period API; gubun=3 is daily in the stock-period contract.
        data=call("/gbstock/quote/v1/period",{
            "iem_cd":code,"end_dt":end,"count":"0012","maxavg":"005",
            "gubun":"3","xtick":"0001","today_cls":"0","market_cls":"0",
        })
        return parse_daily_rows(data,"US")

    def history_loop(self):
        idx={"KR":0,"US":0}
        while not self._stop.is_set():
            for market in ("KR","US"):
                codes=self.fixed[market]
                code=codes[idx[market]%len(codes)];idx[market]+=1
                try:
                    bars=self._fetch_kr_daily(code) if market=="KR" else self._fetch_us_daily(code)
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

    def _read_krx_indices(self):
        text=self._krx_home_text();status=self._krx_status();out={}
        for key,raw,label in (("kospi","KOSPI","코스피"),("kosdaq","KOSDAQ","코스닥")):
            v,ch,pct=self._parse_krx_home_index(text,raw)
            out[key]=self._market_item(label,v,ch,pct,status,"KRX 공식",self._update_krx_series(key,v,ch))
        return out

    def krx_loop(self):
        while not self._stop.is_set():
            try:self.market.update(self._read_krx_indices());self.market_errors.pop("krx_indices",None)
            except Exception as exc:self.market_errors["krx_indices"]=str(exc)[:500]
            self.market_updated_at=time.time();self._stop.wait(60)

    def _symbol_candidates(self,key):
        configured=self.index_symbols.get(key,"")
        defaults={"sp500":["SPX","N@SPX"],"nasdaq":["COMP","IXIC","NDX","N@IXIC"],"sox":["SOX","PHLXSOX","N@SOX"]}
        out=[configured] if configured else []
        for x in defaults.get(key,[]):
            if x not in out:out.append(x)
        return out

    def _read_symbol_period_one(self,symbol,label,status="종가 기준"):
        from nhplug import call
        today=datetime.now(KST).strftime("%Y%m%d")
        data=call("/gbstock/quote/v1/symbolIndexFxPeriod",{
            "iem_cd":symbol,"end_dt":today,"array_cnt":12,"maxavg":"005","gubun":"1","xtick":"001","today_cls":"0","scale_change":"0"
        })
        value=pick(data,("close_prc","ovrs_prpr","last","close","prpr"))
        sign=pick_text(data,("prdy_vrss_sign","sign"))
        change=signed_value(pick(data,("prdy_vrss","change")),sign)
        pct=signed_value(pick(data,("prdy_ctrt","change_rate")),sign)
        rows=first_list(data,("Output_1","output_1"));series=[];asof=""
        for r in rows:
            v=num(r.get("close_prc") or r.get("ovrs_prpr") or r.get("close") or r.get("last"))
            if v:series.append(v)
            if not asof:asof=normalize_date(r.get("bsop_date") or r.get("xymd") or r.get("date"))
        if not value and series:value=series[0]
        if value<=0:raise RuntimeError(f"{label} value missing for {symbol}")
        asof=asof or today
        return self._market_item(label,value,change,pct,f"{status} · {asof[:4]}-{asof[4:6]}-{asof[6:]}","NHPLUG",list(reversed(series)),asof)

    def _read_symbol_period(self,key,label,status="종가 기준"):
        errs=[]
        for s in self._symbol_candidates(key):
            try:
                x=self._read_symbol_period_one(s,label,status);self.index_symbols[key]=s;return x
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
        return self._market_item("필라델피아 반도체지수",v,ch,pct,f"공식값 · {asof[:4]}-{asof[4:6]}-{asof[6:]}",
                                 "Nasdaq 공식",[prev,v] if prev>0 else [v],asof)

    def _discover_futures(self):
        try:
            from nhplug.instruments import load_master
            if not self.future_symbols["kospi_night"]:
                for row in dataframe_rows(load_master("m_future")):
                    code=str(row.get("code") or row.get("sCode") or "").strip().upper()
                    name=str(row.get("name") or row.get("sName") or "")
                    if code.startswith("KA") and ("KOSPI200" in name.upper() or "코스피200" in name):
                        self.future_symbols["kospi_night"]=code;break
            if not self.future_symbols["nasdaq_future"]:
                cand=[]
                for row in dataframe_rows(load_master("fucode_h")):
                    s=str(row.get("isym") or row.get("InnerSymbol") or row.get("symb") or "").strip().upper()
                    name=str(row.get("enam") or row.get("EngName") or "")
                    if "NASDAQ" in name.upper() and s:cand.append((10 if str(row.get("ledm") or "")=="1" else 0,s,str(row.get("exnm") or "FCME").upper()))
                if cand:
                    cand.sort(reverse=True);_,s,e=cand[0];self.future_symbols["nasdaq_future"]=s;self.future_symbols["nasdaq_future_exnm"]=e
        except Exception as exc:self.market_errors["future_master"]=str(exc)[:300]

    def _read_kospi_night(self):
        from nhplug import call
        s=self.future_symbols.get("kospi_night","")
        if not s:raise RuntimeError("코스피 야간선물 종목코드 자동탐색 실패")
        d=call("/krfuture/quote/v1/night",{"iem_cd":s});v=pick(d,("prpr",));sign=pick_text(d,("sign",))
        if v<=0:raise RuntimeError("야간선물 현재가 없음")
        ch=signed_value(pick(d,("vrss",)),sign);pct=signed_value(pick(d,("ctrt",)),sign)
        old=self.market.get("kospi_night",{}).get("series",[])
        return self._market_item("코스피 야간선물",v,ch,pct,"실시간","NHPLUG",(old+[v])[-30:],datetime.now(KST).strftime("%Y%m%d"))

    def _read_nasdaq_future(self):
        from nhplug import call
        s=self.future_symbols.get("nasdaq_future","");e=self.future_symbols.get("nasdaq_future_exnm","FCME")
        if not s:raise RuntimeError("NASDAQ 선물 선도월물 자동탐색 실패")
        d=call("/gbfuture/quote/v1/current",{"exnm":e,"iem_cd":s});v=pick(d,("last",));sign=pick_text(d,("sign",))
        if v<=0:raise RuntimeError("나스닥 선물 현재가 없음")
        ch=signed_value(pick(d,("diff",)),sign);pct=signed_value(pick(d,("rate",)),sign);old=self.market.get("nasdaq_future",{}).get("series",[])
        return self._market_item("나스닥 선물",v,ch,pct,"실시간","NHPLUG",(old+[v])[-30:],datetime.now(KST).strftime("%Y%m%d"))

    def reference_loop(self):
        while not self._stop.is_set():
            for key,label in (("sp500","S&P500"),("nasdaq","나스닥")):
                try:self.market[key]=self._read_symbol_period(key,label);self.market_errors.pop(key,None)
                except Exception as exc:self.market_errors[key]=str(exc)[:500]
            try:
                try:self.market["sox"]=self._read_symbol_period("sox","필라델피아 반도체지수")
                except Exception:self.market["sox"]=self._read_sox_nasdaq()
                self.market_errors.pop("sox",None)
            except Exception as exc:self.market_errors["sox"]=str(exc)[:500]
            self.market_updated_at=time.time();self._stop.wait(60)

    def futures_loop(self):
        self._discover_futures()
        while not self._stop.is_set():
            for key,fn in (("kospi_night",self._read_kospi_night),("nasdaq_future",self._read_nasdaq_future)):
                try:self.market[key]=fn();self.market_errors.pop(key,None)
                except Exception as exc:self.market_errors[key]=str(exc)[:300]
            self.market_updated_at=time.time();self._stop.wait(15)

    def _pending(self,key,label,source="NHPLUG"):
        err=self.market_errors.get(key);status=f"수신 오류 · {err[:100]}" if err else "수신 대기"
        return self._market_item(label,None,None,None,status,source,[])

    def market_state(self,market):
        if str(market).upper()=="KR":
            return [
                self.market.get("kospi") or self._pending("krx_indices","코스피","KRX 공식"),
                self.market.get("kosdaq") or self._pending("krx_indices","코스닥","KRX 공식"),
                self.market.get("kospi_night") or self._pending("kospi_night","코스피 야간선물"),
                self.market.get("nasdaq_future") or self._pending("nasdaq_future","나스닥 선물"),
                self.market.get("sox") or self._pending("sox","필라델피아 반도체지수"),
            ]
        return [
            self.market.get("sp500") or self._pending("sp500","S&P500"),
            self.market.get("nasdaq") or self._pending("nasdaq","나스닥"),
            self.market.get("nasdaq_future") or self._pending("nasdaq_future","나스닥 선물"),
            self.market.get("sox") or self._pending("sox","필라델피아 반도체지수"),
        ]

    def health(self):
        return {"nh_realtime":self.connected_any(),"realtime":dict(self.connected),"errors":dict(self.errors),
                "kr_tracked":len(self.fixed["KR"]),"kr_priced":sum(q.price>0 for q in self.quotes["KR"].values()),
                "us_tracked":len(self.fixed["US"]),"us_priced":sum(q.price>0 for q in self.quotes["US"].values()),
                "market_updated_at":self.market_updated_at,"market_errors":dict(self.market_errors),
                "usdkrw":self.usdkrw,"usdkrw_asof":self.usdkrw_asof,"usdkrw_tradeable":self.usdkrw_tradeable,
                "usdkrw_source":self.usdkrw_source,"program_realtime":dict(self.program_realtime),
                "investor_updated_at":self.investor_updated_at,"history_updated_at":self.history_updated_at}

    def start(self):
        for target in (self.kr_scanner,self.investor_loop,self.program_loop,self.us_scanner,
                       self.history_loop,self.krx_loop,self.reference_loop,self.futures_loop):
            threading.Thread(target=target,daemon=True).start()
