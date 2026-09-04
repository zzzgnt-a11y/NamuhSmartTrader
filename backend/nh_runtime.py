from __future__ import annotations
import os, time, threading, logging, re
from typing import Any, Dict
from .models import QuoteState

log=logging.getLogger("nh_runtime")

PRICE_KEYS=("stck_prpr","price","prc","cur_pr","now_pr","last","last_price")
OPEN_KEYS=("stck_oprc","open","open_pr","open_price")
HIGH_KEYS=("stck_hgpr","high","high_pr")
LOW_KEYS=("stck_lwpr","low","low_pr")
VOL_KEYS=("acml_vol","volume","vol","acc_volume")
PER_KEYS=("per","per_val","per_value")
PBR_KEYS=("pbr","pbr_val","pbr_value")
FOREIGN_KEYS=("frgn_ntby_qty","foreign_net","frgn_net")
INST_KEYS=("orgn_ntby_qty","institution_net","inst_net")

def _walk(o: Any):
    if isinstance(o, dict):
        yield o
        for v in o.values(): yield from _walk(v)
    elif isinstance(o, list):
        for v in o: yield from _walk(v)

def _num(v):
    try:
        if v is None or v=="": return 0.0
        return float(str(v).replace(",","").replace("+",""))
    except Exception:
        return 0.0

def pick(data: Any, keys):
    for d in _walk(data):
        for k in keys:
            if k in d:
                n=_num(d.get(k))
                if n!=0: return n
    return 0.0

def pick_code(data: Any):
    for d in _walk(data):
        for k in ("iem_cd","code","symbol","tr_key","stock_code","stck_shrn_iscd"):
            v=d.get(k)
            if v and re.fullmatch(r"\d{6}", str(v)): return str(v)
    return ""

class NhRuntime:
    """
    2단계 시장 수집:
    1) 전 KRX 마스터를 REST 호출한도에 맞춰 순환 스캔
    2) 스캔 결과의 상위 급수급 후보만 NH KRX WebSocket으로 승격

    따라서 후보 종목의 가격은 tick 실시간이며,
    '전 종목 발견'은 API 호출한도 때문에 순환주기 방식이다.
    """
    def __init__(self):
        self.quotes: Dict[str,QuoteState]={}
        self.connected=False
        self.last_error=""
        self._stop=False
        self.fixed_codes=[x.strip() for x in os.getenv("TRACKED_CODES","").split(",") if x.strip()]
        self.all_codes=[]
        self.scan_index=0
        self.scan_cycle_seconds=0.0
        self.last_scan_cycle_at=0.0

    @property
    def codes(self):
        return self.all_codes or self.fixed_codes

    def state(self, code:str):
        if code not in self.quotes: self.quotes[code]=QuoteState(code=code,name=code)
        return self.quotes[code]

    def load_market_master(self):
        try:
            from nhplug.instruments import load_master
            df=load_master("m_new_stock")
            cols=[str(c) for c in df.columns]
            # 헤더 개정에 견디도록 코드/이름/업종 후보를 휴리스틱 탐색
            code_col=next((c for c in cols if any(k in c.lower() for k in ("short_code","shrt","iem_cd","stock_code","단축","종목코드"))),None)
            if code_col is None:
                for c in cols:
                    sample=" ".join(str(x) for x in df[c].head(20).tolist())
                    if re.search(r"\b\d{6}\b",sample): code_col=c; break
            name_col=next((c for c in cols if any(k in c.lower() for k in ("name","kor_nm","한글","종목명"))),None)
            sector_col=next((c for c in cols if any(k in c.lower() for k in ("sector","industry","업종"))),None)

            rows=[]
            if code_col:
                for _,r in df.iterrows():
                    raw=str(r.get(code_col,"")).strip()
                    m=re.search(r"(\d{6})",raw)
                    if not m: continue
                    code=m.group(1)
                    q=self.state(code)
                    if name_col: q.name=str(r.get(name_col,"") or code).strip()
                    if sector_col: q.sector=str(r.get(sector_col,"") or "").strip()
                    rows.append(code)
            self.all_codes=list(dict.fromkeys(rows))
            log.info("KRX master loaded: %d codes",len(self.all_codes))
        except Exception as e:
            self.last_error=f"master: {e}"
            self.all_codes=list(dict.fromkeys(self.fixed_codes))

    def _apply_rest(self, code, data):
        q=self.state(code)
        p=pick(data,PRICE_KEYS)
        if p: q.mark(p,pick(data,VOL_KEYS))
        q.open=pick(data,OPEN_KEYS) or q.open
        q.high=pick(data,HIGH_KEYS) or q.high
        q.low=pick(data,LOW_KEYS) or q.low
        q.per=pick(data,PER_KEYS) or q.per
        q.pbr=pick(data,PBR_KEYS) or q.pbr
        q.foreign_net=pick(data,FOREIGN_KEYS) or q.foreign_net
        q.institution_net=pick(data,INST_KEYS) or q.institution_net

    def seed_fixed(self):
        try:
            from nhplug import call
            for code in self.fixed_codes:
                if self._stop: return
                try:
                    data=call("/krstock/quote/v1/currentPrice", {"iem_cd":code,"market_cd":"KRX"})
                    self._apply_rest(code,data)
                except Exception as e:
                    log.warning("seed %s failed: %s",code,e)
                time.sleep(0.30)
        except Exception as e:
            self.last_error=str(e)

    def scanner_forever(self):
        self.load_market_master()
        codes=self.all_codes or self.fixed_codes
        if not codes:
            self.last_error="KRX 종목마스터/TRACE_CODES 없음"; return
        try:
            from nhplug import call
        except Exception as e:
            self.last_error=str(e); return

        cycle_start=time.time()
        while not self._stop:
            code=codes[self.scan_index % len(codes)]
            self.scan_index=(self.scan_index+1)%len(codes)
            try:
                data=call("/krstock/quote/v1/currentPrice", {"iem_cd":code,"market_cd":"KRX"})
                self._apply_rest(code,data)
            except Exception as e:
                # 429는 SDK가 재시도하지 않으므로 스캐너도 속도를 낮춘다.
                msg=str(e)
                self.last_error=msg[:300]
                if "429" in msg or "rate" in msg.lower(): time.sleep(1.0)

            if self.scan_index==0:
                self.scan_cycle_seconds=time.time()-cycle_start
                self.last_scan_cycle_at=time.time()
                cycle_start=time.time()
            time.sleep(0.27)  # 초당 4회보다 여유 있게

    def _on_tick(self, msg):
        try:
            code=pick_code(msg)
            if not code: return
            q=self.state(code)
            p=pick(msg,PRICE_KEYS); v=pick(msg,VOL_KEYS)
            if p:
                q.mark(p,v)
                self.connected=True
        except Exception as e:
            self.last_error=str(e)

    def priority_codes(self, n=10):
        scored=[]
        now=time.time()
        for code,q in self.quotes.items():
            if q.price<=0: continue
            chg=abs((q.price/q.open-1)*100) if q.open>0 else 0
            freshness=max(0, 1-(now-q.updated_at)/600) if q.updated_at else 0
            value=q.price*q.volume
            score=chg*3 + freshness*3 + (1 if value>0 else 0)
            scored.append((score,code))
        scored.sort(reverse=True)
        top=[c for _,c in scored[:n]]
        # 고정 감시코드가 완전히 사라지지 않도록 일부 포함
        for c in self.fixed_codes:
            if c not in top:
                top.append(c)
            if len(top)>=n: break
        return top[:n]

    def websocket_forever(self):
        while not self._stop:
            keys=self.priority_codes(10)
            if not keys:
                keys=self.fixed_codes[:10]
            if not keys:
                time.sleep(3); continue
            try:
                from nhplug.realtime import subscribe
                # 일정 메시지마다 종료해 급수급 상위 후보 구독목록을 갱신한다.
                subscribe(keys, self._on_tick, max_messages=200)
            except Exception as e:
                self.connected=False
                self.last_error=str(e)[:300]
                time.sleep(2)

    def start(self):
        threading.Thread(target=self.seed_fixed,daemon=True).start()
        threading.Thread(target=self.scanner_forever,daemon=True).start()
        threading.Thread(target=self.websocket_forever,daemon=True).start()

    def stop(self): self._stop=True
