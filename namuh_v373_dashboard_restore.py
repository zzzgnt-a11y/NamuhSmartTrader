from __future__ import annotations

import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
_INSTALLED = False


def _f(v, default=0.0):
    try:
        return float(v)
    except Exception:
        return float(default)


def _route(core, path):
    return next(
        (r for r in core.app.routes if getattr(r, "path", None) == path and hasattr(r, "dependant")),
        None,
    )


def _cached_top5(core, market):
    market = str(market or "").upper()
    if market not in ("KR", "US"):
        return []
    try:
        with core.cache_lock:
            rows = list((core.CACHE.get(market) or {}).get("scalp") or [])
    except Exception:
        rows = []
    rows.sort(key=lambda x: _f(x.get("score")), reverse=True)
    return rows[:5]


def _install_safe_state_routes(core):
    """Repair v372 route binding and preserve a visible latest TOP5 after close.

    Trading stays gated by candidate_scan_active/trading_window. Only the dashboard
    display gets the latest cached AI ranking when the market is closed.
    """
    installed = {"state": False, "coin": False}

    state_route = _route(core, "/api/state")
    original_state = getattr(core, "state", None)
    if state_route is not None and callable(original_state):
        def state_safe(**kwargs):
            out = original_state(**kwargs)
            if not isinstance(out, dict):
                return out

            mode = str(out.get("mode") or kwargs.get("market") or "").upper()
            rows = list(out.get("scalp") or [])
            if mode in ("KR", "US") and not rows:
                rows = _cached_top5(core, mode)
                if rows:
                    out["candidate_display_source"] = "latest_cache_after_close"
            rows.sort(key=lambda x: _f(x.get("score")), reverse=True)
            out["scalp"] = rows[:5]
            out["candidate_display_count"] = len(out["scalp"])
            out["candidate_display_live"] = bool(out.get("candidate_scan_active"))
            return out

        state_safe._namuh_v373_safe_state = True
        state_safe._old = original_state
        state_route.dependant.call = state_safe
        state_route.endpoint = state_safe
        state_route._namuh_v372_trim = True
        state_route._namuh_v373_restored = True
        installed["state"] = True

    coin_route = _route(core, "/api/coin/state")
    original_coin_state = getattr(core, "coin_state", None)
    if coin_route is not None and callable(original_coin_state):
        def coin_state_safe(**_kwargs):
            out = original_coin_state()
            if isinstance(out, dict):
                rows = list(out.get("candidates") or [])
                rows.sort(key=lambda x: _f(x.get("score")), reverse=True)
                out["candidates"] = rows[:5]
            return out

        coin_state_safe._namuh_v373_safe_coin = True
        coin_state_safe._old = original_coin_state
        coin_route.dependant.call = coin_state_safe
        coin_route.endpoint = coin_state_safe
        coin_route._namuh_v372_trim = True
        coin_route._namuh_v373_restored = True
        installed["coin"] = True

    return installed


def _patch_frontend(build):
    p = ROOT / "static/app.js"
    if not p.exists():
        return False
    try:
        text = p.read_text(encoding="utf-8")
        old = text

        # Keep the last ranked TOP5 visible after the market closes. Trading remains
        # disabled because candidate_scan_active is still false on the backend.
        text = text.replace(
            'text("topScalp",scan&&scalp[0]?`${scalp[0].name} ${Number(scalp[0].score).toFixed(0)}점`:scan?"분석 중":"장 종료");',
            'text("topScalp",scalp[0]?`${scalp[0].name} ${Number(scalp[0].score).toFixed(0)}점${scan?"":" · 장마감"}`:scan?"분석 중":"장 종료");'
        )
        text = text.replace(
            '$("candidateClosed")?.classList.toggle("hide",scan);$("candidateZone")?.classList.toggle("hide",!scan);',
            'const showCandidates=scalp.length>0;$("candidateClosed")?.classList.toggle("hide",scan);$("candidateZone")?.classList.toggle("hide",!showCandidates);'
        )
        text = text.replace(
            'if(scan){html("scalpList",scalp.length?scalp.map((x,i)=>candidateCard(x,false,i+1)).join(""):\'<div class="empty">후보 데이터 축적 중</div>\');',
            'if(scan||scalp.length){html("scalpList",scalp.length?scalp.map((x,i)=>candidateCard(x,false,i+1)).join(""):\'<div class="empty">후보 데이터 축적 중</div>\');'
        )
        text = text.replace(
            'text("topSector",lead?(scan?`${lead.sector} · 대장주 : ${lead.leader||"-"}`:`${lead.sector} · 장 종료`):"분석 중");',
            'text("topSector",lead?`${lead.sector}${scan?` · 대장주 : ${lead.leader||"-"}`:" · 장마감 최신값"}`:"분석 중");'
        )

        if text != old:
            p.write_text(text, encoding="utf-8")
            return True
        return False
    except Exception as exc:
        print("V373 frontend patch error:", str(exc)[:160], flush=True)
        return False


def _install_health(core, installed, frontend):
    old = core.health_payload
    if getattr(old, "_namuh_v373_dashboard_restore", False):
        return

    def health():
        data = dict(old())
        data["v373"] = {
            "active": True,
            "dashboard_restore": True,
            "route_binding_repair": True,
            "kr_us_state_route_restored": bool(installed.get("state")),
            "coin_state_route_restored": bool(installed.get("coin")),
            "top5_preserved": True,
            "after_close_top5_visible": True,
            "frontend_after_close_patch": bool(frontend),
            "trading_gate_unchanged": True,
            "layout_unchanged": True,
        }
        return data

    health._namuh_v373_dashboard_restore = True
    health._old = old
    core.health_payload = health


def apply(ns=None):
    global _INSTALLED
    if _INSTALLED:
        return True
    core = ns.get("core") if isinstance(ns, dict) else None
    if core is None:
        return False
    _INSTALLED = True

    installed = _install_safe_state_routes(core)
    build = (os.getenv("RENDER_GIT_COMMIT") or os.getenv("GY_BUILD_ID") or "v373")[:12]
    frontend = _patch_frontend(build)
    _install_health(core, installed, frontend)
    print(
        "NAMUH V373 DASHBOARD ROUTE/TOP5 REPAIR active: "
        f"state={installed['state']} coin={installed['coin']} frontend={frontend} "
        "latest TOP5 visible after close; trading gate unchanged",
        flush=True,
    )
    return True
