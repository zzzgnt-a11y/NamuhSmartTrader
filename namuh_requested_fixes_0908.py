from __future__ import annotations

import re
from pathlib import Path

_INSTALLED = False

# User-requested relative technical importance, highest -> lowest.
# These are RELATIVE weights (sum 112), normalized back to the 45-point Standard bucket.
TECH_WEIGHTS = {
    "거래량": 22.0,
    "RSI": 20.0,
    "볼린저": 18.0,
    "MACD": 16.0,
    "이평": 14.0,
    "가격구조": 12.0,
    "엘리어트": 10.0,
}
TECH_MAX = {
    "거래량": 15.0,
    "RSI": 10.0,
    "볼린저": 10.0,
    "MACD": 10.0,
    "이평": 10.0,
    "가격구조": 10.0,
    "엘리어트": 10.0,
}


def _f(v, default=0.0):
    try:
        return float(v)
    except Exception:
        return float(default)


def _clamp(v, lo=0.0, hi=100.0):
    return max(float(lo), min(float(hi), _f(v)))


def _weighted_standard45(raw):
    denom = sum(TECH_WEIGHTS.values())
    if denom <= 0:
        return 0.0, {}
    parts = {}
    total = 0.0
    for k, w in TECH_WEIGHTS.items():
        mx = TECH_MAX[k]
        ratio = _clamp(_f((raw or {}).get(k)) / mx if mx > 0 else 0, 0, 1)
        contribution = ratio * (w / denom) * 45.0
        parts[k] = round(contribution, 3)
        total += contribution
    return round(_clamp(total, 0, 45), 1), parts


def _install_search_restore(root: Path):
    js = root / "static" / "v34.js"
    css = root / "static" / "v34.css"

    old_position = "function positionSearchResults(){const result=q('#v34SearchResults'),input=q('#v34SearchInput');if(!result||!input)return;if(innerWidth>780){result.style.position='';result.style.left='';result.style.right='';result.style.top='';result.style.maxHeight='';result.style.zIndex='';return}const vv=window.visualViewport,viewTop=vv?.offsetTop||0,viewH=vv?.height||innerHeight,rect=input.getBoundingClientRect();let top=Math.max(viewTop+8,rect.bottom+8);const viewBottom=viewTop+viewH;if(viewBottom-top<150)top=Math.max(viewTop+56,viewBottom-260);result.style.position='fixed';result.style.left='10px';result.style.right='10px';result.style.top=`${Math.round(top)}px`;result.style.maxHeight=`${Math.max(130,Math.floor(viewBottom-top-10))}px`;result.style.zIndex='10050'}"
    new_position = "function positionSearchResults(){const result=q('#v34SearchResults');if(!result)return;result.style.position='';result.style.left='';result.style.right='';result.style.top='';result.style.maxHeight='';result.style.zIndex=''}"

    text = js.read_text(encoding="utf-8")
    text = text.replace(old_position, new_position)
    text = text.replace("window.visualViewport?.addEventListener('resize',positionSearchResults);window.visualViewport?.addEventListener('scroll',positionSearchResults);", "")
    js.write_text(text, encoding="utf-8")

    marker = "/* NAMUH_SEARCH_ORIGINAL_STABLE_0908 */"
    c = css.read_text(encoding="utf-8")
    c = re.sub(r"/\* NAMUH_SEARCH_ORIGINAL_STABLE_0908 \*/.*?/\* END_NAMUH_SEARCH_ORIGINAL_STABLE_0908 \*/\s*", "", c, flags=re.S)
    c += r'''
/* NAMUH_SEARCH_ORIGINAL_STABLE_0908 */
@media(max-width:780px){
  #v34SearchBox{display:block!important;position:relative!important}
  #v34SearchResults.v34-search-results{
    position:absolute!important;left:12px!important;right:12px!important;top:72px!important;
    max-height:330px!important;z-index:10050!important;transform:none!important;
    animation:none!important;transition:none!important;
  }
}
@media(max-width:480px){
  #v34SearchResults.v34-search-results{
    position:absolute!important;left:12px!important;right:12px!important;top:72px!important;max-height:330px!important;
  }
}
/* END_NAMUH_SEARCH_ORIGINAL_STABLE_0908 */
'''
    css.write_text(c, encoding="utf-8")


def apply(ns=None):
    global _INSTALLED
    if _INSTALLED:
        return True
    core = ns.get("core") if isinstance(ns, dict) else None
    if core is None:
        return False

    # 1) Sector mapping: do not collapse a live stock to "기타" merely because
    # q.sector was never populated. The KR master already contains the sector.
    old_sector_name = getattr(core, "sector_name", None)
    if callable(old_sector_name) and not getattr(old_sector_name, "_namuh_master_sector", False):
        def sector_name(q, market):
            m = str(market or "").upper()
            sec = str(getattr(q, "sector", "") or "").strip()
            generic = {"", "기타", "기타업종", "업종 미분류", "미분류"}
            if m == "KR" and sec in generic:
                try:
                    meta = dict((getattr(core.feed, "kr_master_meta", {}) or {}).get(str(getattr(q, "code", "")).upper()) or {})
                    master_sec = str(meta.get("sector") or "").strip()
                    if master_sec and master_sec not in generic:
                        q.sector = master_sec
                        return master_sec
                except Exception:
                    pass
            if sec and sec not in generic:
                return sec
            return old_sector_name(q, market)
        sector_name._namuh_master_sector = True
        core.sector_name = sector_name

    # 2/3) Absolute-final C1 owner for leading-sector bonus + weighted Standard45.
    old_candidate = core.candidate
    if not getattr(old_candidate, "_namuh_requested_0908", False):
        def candidate(*args, **kwargs):
            out = old_candidate(*args, **kwargs)
            if not isinstance(out, dict):
                return out
            try:
                q = args[0] if args else kwargs.get("q")
                market = str(args[1] if len(args) > 1 else kwargs.get("market", "")).upper()
                smart = bool(args[2] if len(args) > 2 else kwargs.get("smart", False))
                if q is None or smart or market not in ("KR", "US"):
                    return out
                c1 = dict(out.get("condition1") or {})
                if not c1:
                    return out

                bd = dict(c1.get("breakdown") or {})
                gates = dict(c1.get("gates") or {})
                raw = dict(c1.get("standard_raw") or {})
                std45, weighted_parts = _weighted_standard45(raw)
                bd["standard45"] = std45

                bonus = _f(c1.get("bonus_score"))
                if market == "KR":
                    try:
                        import namuh_conditions_final_patch as final_rules
                        sector_rankmap = args[6] if len(args) > 6 else kwargs.get("sector_rankmap")
                        bonus, bonus_bd = final_rules._bonus15(core, q, out, sector_rankmap)
                        for k, v in bonus_bd.items():
                            bd[k] = v
                        c1["sector"] = core.sector_name(q, "KR")
                        c1["leading_sector_rank"] = out.get("sector_rank")
                        c1["leading_sector_active"] = bool(out.get("sector_rank") is not None and int(out.get("sector_rank") or 999) <= 5)
                    except Exception as exc:
                        c1["leading_sector_error"] = str(exc)[:160]

                prereq = round(
                    _f(bd.get("daily10")) + _f(bd.get("minute10")) +
                    _f(bd.get("execution12")) + _f(bd.get("orderbook8")), 1
                )
                bonus = round(
                    _f(bd.get("sector_relative7_5")) +
                    _f(bd.get("leading_sector_flow3_75")) +
                    _f(bd.get("news3_75")), 2
                )
                blocked = bool(gates.get("event_block", False))
                total = round(_clamp(prereq + std45 + bonus, 0, 100), 1)
                if blocked:
                    total = 0.0
                threshold = _f(c1.get("entry_threshold"), 72.0)
                hard = bool(gates.get("daily") and gates.get("minute1m") and gates.get("execution") and gates.get("orderbook"))
                gate = bool(not blocked and hard and total >= threshold)
                gates["total72"] = total >= threshold

                tm = dict(c1.get("technical_meta") or {})
                denom = sum(TECH_WEIGHTS.values())
                tm["weight_model"] = {
                    "order": list(TECH_WEIGHTS.keys()),
                    "relative_weights": dict(TECH_WEIGHTS),
                    "normalized_percent": {k: round(v / denom * 100.0, 2) for k, v in TECH_WEIGHTS.items()},
                    "standard45_contribution": weighted_parts,
                    "formula": "indicator_score/max * relative_weight, then normalize to 45",
                }
                c1.update({
                    "score": total, "gate": gate, "breakdown": bd, "gates": gates,
                    "prerequisite_score": prereq, "standard_score": std45, "bonus_score": bonus,
                    "technical_meta": tm,
                    "standard_weight_model": "22-20-18-16-14-12-10 relative -> normalized 45",
                })
                out["condition1"] = c1
                out["condition1_score"] = total
                out["score"] = total
                out["priority_score"] = total

                labels = [x for x in list(out.get("condition_labels") or []) if str(x) != "조건1"]
                if gate:
                    labels.insert(0, "조건1")
                out["condition_labels"] = list(dict.fromkeys(labels))
                out["condition_display"] = "복합조건" if len([x for x in out["condition_labels"] if str(x).startswith("조건")]) > 1 else (out["condition_labels"][0] if out["condition_labels"] else "")
            except Exception as exc:
                out["requested_fix_0908_error"] = str(exc)[:220]
            return out
        candidate._namuh_requested_0908 = True
        core.candidate = candidate

    # 4) Restore the original v34 search UI, but remove the mobile visualViewport
    # fixed-position behavior that caused the flicker.
    try:
        _install_search_restore(Path(__file__).resolve().parent)
    except Exception as exc:
        print("NAMUH SEARCH RESTORE ERROR:", str(exc)[:180], flush=True)

    old_health = getattr(core, "health_payload", None)
    if callable(old_health):
        def health():
            d = dict(old_health())
            try:
                sectors = list((getattr(core, "CACHE", {}) or {}).get("KR", {}).get("sectors", []) or [])
            except Exception:
                sectors = []
            d["requested_fixes_0908"] = {
                "active": True,
                "sector_master_count": len(getattr(core.feed, "kr_master_meta", {}) or {}),
                "sector_catalog_count": len(getattr(core.feed, "sector_catalog", {}) or {}),
                "leading_sectors": [{"sector":x.get("sector"),"rank":i+1,"score":x.get("score")} for i,x in enumerate(sectors[:5])],
                "technical_weights": dict(TECH_WEIGHTS),
                "search": "original v34 restored; visualViewport fixed-position disabled",
            }
            return d
        core.health_payload = health

    _INSTALLED = True
    print("NAMUH REQUESTED FIXES 0908 active: sector/bonus + weighted45 + original search stable", flush=True)
    return True
