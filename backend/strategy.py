from __future__ import annotations
from .indicators import sma, rsi, williams_r, macd, bollinger, dmi_proxy

def scalp_score(q, sector_score: float = 0.0, disclosure_score: float = 0.0):
    px=list(q.prices)
    if len(px)<20 or q.price<=0:
        return 0.0, ["지표 데이터 축적 중"]

    score=0.0; reasons=[]
    m,s=macd(px)
    rv=rsi(px,14)
    wr=williams_r(px,14)
    ma5,ma10,ma20=sma(px,5),sma(px,10),sma(px,20)
    mid,upper,lower=bollinger(px,20)
    pdi,mdi,adx=dmi_proxy(px,14)

    if m>s: score+=10; reasons.append("MACD 우위")
    if 50<=rv<=72: score+=10; reasons.append(f"RSI {rv:.0f}")
    elif rv>82: score-=8; reasons.append("RSI 과열감점")
    if -70<=wr<=-15: score+=5; reasons.append("Williams %R 양호")
    if ma5>ma10>ma20: score+=15; reasons.append("5>10>20 정배열/골든구조")
    if q.price>mid and q.price<upper: score+=8; reasons.append("볼린저 상단 전 추세")
    if pdi>mdi and adx>=12: score+=10; reasons.append("DMI +DI 우위")

    # 현재 누적거래량 vs 이전 기준치
    if q.prev_volume>0:
        vr=q.volume/q.prev_volume
        if vr>=1.5: score+=10; reasons.append(f"거래량 {vr:.1f}배")

    # 체결강도 대용: 서버가 매수/매도 누적을 얻었을 때 계산
    buy=getattr(q,"buy_volume",0.0); sell=getattr(q,"sell_volume",0.0)
    strength=(buy/max(sell,1))*100 if buy>0 or sell>0 else 100
    if strength>=105: score+=10; reasons.append(f"체결강도 {strength:.0f}")

    if sector_score>0:
        add=min(15.0,sector_score); score+=add; reasons.append(f"주도섹터 +{add:.0f}")
    if disclosure_score>0:
        add=min(7.0,disclosure_score); score+=add; reasons.append(f"공시/호재 +{add:.0f}")

    return max(0.0,min(100.0,round(score,1))), reasons

def smart_score(q, sector_per: float = 0.0, sector_pbr: float = 0.0):
    px=list(q.prices)
    if len(px)<20 or q.price<=0:
        return 0.0, ["지표 데이터 축적 중"]
    score=0.0; reasons=[]
    if 0<q.per<=15: score+=15; reasons.append(f"PER {q.per:.2f}")
    if 0<q.pbr<=1.5: score+=15; reasons.append(f"PBR {q.pbr:.2f}")
    if sector_per>0 and 0<q.per<sector_per*.85: score+=8; reasons.append("업종 PER 할인")
    if sector_pbr>0 and 0<q.pbr<sector_pbr*.85: score+=7; reasons.append("업종 PBR 할인")
    if q.foreign_net>0: score+=12; reasons.append("외국인 순매수")
    if q.institution_net>0: score+=12; reasons.append("기관 순매수")

    ma5,ma20=sma(px,5),sma(px,20)
    rv=rsi(px,14)
    if ma5>=ma20 and rv<72: score+=8; reasons.append("과열 전 완만한 추세")
    gain=(px[-1]/px[-6]-1)*100 if len(px)>=6 and px[-6]>0 else 0
    if gain<8 and ma5>=ma20: score+=8; reasons.append("급등 전 누적 흐름")
    return max(0.0,min(100.0,round(score,1))), reasons
