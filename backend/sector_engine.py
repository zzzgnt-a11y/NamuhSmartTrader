from __future__ import annotations
from collections import defaultdict

# 기본 종목-섹터 맵. 종목마스터 업종 필드가 준비되면 자동맵으로 확장 가능.
DEFAULT_MAP={
"005930":"반도체","000660":"반도체","042700":"반도체",
"035420":"인터넷/AI","035720":"인터넷/AI",
"068270":"바이오","012450":"방산","267260":"전력기기"
}

def leading(quotes):
    agg=defaultdict(lambda:{"n":0,"chg":0.0,"money":0.0,"leader":"","leader_chg":-1e9})
    for code,q in quotes.items():
        sec=q.sector or DEFAULT_MAP.get(code,"기타")
        if q.open<=0 or q.price<=0: continue
        chg=(q.price/q.open-1)*100
        a=agg[sec]; a["n"]+=1; a["chg"]+=chg; a["money"]+=q.price*q.volume
        if chg>a["leader_chg"]:
            a["leader_chg"]=chg; a["leader"]=q.name or code
    rows=[]
    for sec,a in agg.items():
        if a["n"]<=0: continue
        avg=a["chg"]/a["n"]
        # 수급/거래대금과 동반상승을 함께 반영
        strength=max(0,min(15,avg*2 + (2 if a["money"]>0 else 0)))
        rows.append({"sector":sec,"change_pct":avg,"leader":a["leader"],"score":strength})
    rows.sort(key=lambda x:x["score"],reverse=True)
    return rows[:8]
