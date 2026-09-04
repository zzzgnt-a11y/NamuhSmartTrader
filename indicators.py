from __future__ import annotations
import math

def sma(xs, n):
    return sum(xs[-n:])/n if len(xs) >= n else None

def ema(xs, n):
    if not xs: return None
    a = 2/(n+1)
    v = float(xs[0])
    for x in xs[1:]:
        v = a*float(x)+(1-a)*v
    return v

def rsi(xs, n=14):
    if len(xs) < 2: return 50.0
    up=dn=0.0
    for i in range(max(1,len(xs)-n),len(xs)):
        d=xs[i]-xs[i-1]
        if d>0: up+=d
        else: dn-=d
    if dn==0: return 100.0
    return 100-100/(1+(up/max(1,n))/(dn/max(1,n)))

def williams_r(xs, n=14):
    if not xs: return -50.0
    w=xs[-n:]; hi=max(w); lo=min(w)
    return -50.0 if hi==lo else -100*(hi-w[-1])/(hi-lo)

def macd(xs):
    if len(xs)<3: return (0.0,0.0)
    m=(ema(xs,12) or 0)-(ema(xs,26) or 0)
    vals=[]
    lo=max(2,len(xs)-9)
    for cut in range(lo,len(xs)+1):
        p=xs[:cut]
        vals.append((ema(p,12) or 0)-(ema(p,26) or 0))
    return m, (ema(vals,9) or m)

def bollinger(xs,n=20,k=2):
    if len(xs)<n: return (None,None,None)
    w=xs[-n:]; mid=sum(w)/n
    sd=math.sqrt(sum((x-mid)**2 for x in w)/n)
    return mid,mid+k*sd,mid-k*sd

def dmi_proxy(xs,n=14):
    if len(xs)<n+1: return (0,0,0)
    ups=dns=0.0
    for i in range(len(xs)-n,len(xs)):
        d=xs[i]-xs[i-1]
        ups += max(d,0); dns += max(-d,0)
    den=ups+dns or 1
    p=100*ups/den; m=100*dns/den
    return p,m,abs(p-m)
