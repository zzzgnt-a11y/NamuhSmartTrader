from __future__ import annotations

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


def _install_safe_state_routes(core):
    """Repair the v372 route binding without changing FastAPI's dependency metadata.

    v372 created two wrappers in the same function scope and both captured the same
    local name (``old``). After the second assignment, the /api/state wrapper could
    call coin_state with the ``market`` keyword, producing a 500. Bind each route to
    the known module endpoint instead and keep only the intended TOP5 payload trim.
    """
    installed = {"state": False, "coin": False}

    state_route = _route(core, "/api/state")
    original_state = getattr(core, "state", None)
    if state_route is not None and callable(original_state):
        def state_safe(**kwargs):
            out = original_state(**kwargs)
            if isinstance(out, dict):
                rows = list(out.get("scalp") or [])
                rows.sort(key=lambda x: _f(x.get("score")), reverse=True)
                out["scalp"] = rows[:5]
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
            # The original endpoint has no query parameters. Ignore any stale
            # dependency kwargs defensively so a bad route binding cannot 500.
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


def _install_health(core, installed):
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
    _install_health(core, installed)
    print(
        "NAMUH V373 DASHBOARD ROUTE REPAIR active: "
        f"state={installed['state']} coin={installed['coin']} top5 preserved layout unchanged",
        flush=True,
    )
    return True
