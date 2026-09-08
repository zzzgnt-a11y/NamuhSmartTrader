from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent
_INSTALLED = False


def _patch(rel: str, old: str, new: str) -> bool:
    p = ROOT / rel
    if not p.exists():
        return False
    try:
        text = p.read_text(encoding="utf-8")
        if new in text:
            return True
        if old not in text:
            return False
        p.write_text(text.replace(old, new, 1), encoding="utf-8")
        return True
    except Exception:
        return False


def apply(ns=None):
    global _INSTALLED
    if _INSTALLED:
        return True
    # UI/layout is untouched. Only the arrays handed to the existing candidate
    # renderers are sorted by their unrounded final score and clipped to five.
    stock_ok = _patch(
        "static/app.js",
        "const scalp=s.scalp||[],smart=s.smart||[];",
        "const scalp=(s.scalp||[]).slice().sort((a,b)=>(Number(b.score||0)-Number(a.score||0))||(Number(b.priority_score||0)-Number(a.priority_score||0))).slice(0,5),smart=s.smart||[];",
    )
    coin_ok = _patch(
        "static/coin.js",
        '$("coinCandidateList").innerHTML=(d.candidates||[]).map((x,i)=>candidateCard(x,i,entryScore)).join("")||\'<div class="empty">후보 데이터 축적 중</div>\';',
        '$("coinCandidateList").innerHTML=(d.candidates||[]).slice().sort((a,b)=>Number(b.score||0)-Number(a.score||0)).slice(0,5).map((x,i)=>candidateCard(x,i,entryScore)).join("")||\'<div class="empty">후보 데이터 축적 중</div>\';',
    )
    _INSTALLED = True
    print(f"NAMUH V369 exact TOP5 active: stock={stock_ok} coin={coin_ok} layout unchanged", flush=True)
    return True
