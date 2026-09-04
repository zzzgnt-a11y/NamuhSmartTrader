from __future__ import annotations
import math
from typing import Sequence, Tuple

def sma(xs: Sequence[float], n: int) -> float:
    if len(xs) < n: return float("nan")
    return sum(xs[-n:]) / n

def ema(xs: Sequence[float], n: int) -> float:
    if not xs: return float("nan")
    a = 2.0/(n+1.0)
    v = float(xs[0])
    for x in xs[1:]:
        v = a*float(x)+(1-a)*v
    return v

def rsi(xs: Sequence[float], n: int = 14) -> float:
    if len(xs) < 2: return 50.0
    start=max(1,len(xs)-n)
    up=dn=0.0
    cnt=0
    for i in range(start,len(xs)):
        d=xs[i]-xs[i-1]
        if d>0: up+=d
        else: dn-=d
        cnt+=1
    if cnt==0: return 50.0
    if dn==0: return 100.0
    rs=(up/cnt)/(dn/cnt)
    return 100-100/(1+rs)

def williams_r(xs: Sequence[float], n: int = 14) -> float:
    if not xs: return -50.0
    w=xs[-n:]
    hi=max(w); lo=min(w); c=w[-1]
    return -50.0 if hi==lo else -100*(hi-c)/(hi-lo)

def macd(xs: Sequence[float]) -> Tuple[float,float]:
    m=ema(xs,12)-ema(xs,26)
    # signal approximation from rolling MACD
    vals=[]
    for cut in range(max(2,len(xs)-9),len(xs)+1):
        part=xs[:cut]
        vals.append(ema(part,12)-ema(part,26))
    s=ema(vals,9) if vals else m
    return m,s

def bollinger(xs: Sequence[float], n:int=20, k:float=2.0):
    if len(xs)<n: return (float("nan"),float("nan"),float("nan"))
    w=list(xs[-n:]); mid=sum(w)/n
    var=sum((x-mid)**2 for x in w)/n
    sd=math.sqrt(var)
    return mid,mid+k*sd,mid-k*sd

def dmi_proxy(xs: Sequence[float], n:int=14):
    # tick-price-only proxy. 서버가 OHLC 분봉을 확보하면 정식 DMI로 교체 가능.
    if len(xs)<n+1: return (0.0,0.0,0.0)
    ups=[]; dns=[]
    for i in range(len(xs)-n, len(xs)):
        d=xs[i]-xs[i-1]
        ups.append(max(d,0)); dns.append(max(-d,0))
    su=sum(ups); sd=sum(dns); den=su+sd or 1
    pdi=100*su/den; mdi=100*sd/den
    adx=abs(pdi-mdi)
    return pdi,mdi,adx
