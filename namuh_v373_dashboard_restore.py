from __future__ import annotations

_INSTALLED = False


def _restore_trimmed_route(core, path):
    route = next((r for r in core.app.routes if getattr(r, "path", None) == path and hasattr(r, "dependant")), None)
    if route is None or not getattr(route, "_namuh_v372_trim", False):
        return False

    current = route.dependant.call
    original = None
    try:
        for cell in list(getattr(current, "__closure__", None) or []):
            try:
                obj = cell.cell_contents
            except Exception:
                continue
            if callable(obj) and obj is not current:
                original = obj
                break
    except Exception:
        original = None

    if not callable(original):
        return False

    route.dependant.call = original
    route.endpoint = original
    route._namuh_v372_trim = False
    route._namuh_v373_restored = True
    return True


def _install_health(core, restored):
    old = core.health_payload
    if getattr(old, "_namuh_v373_dashboard_restore", False):
        return

    def health():
        data = dict(old())
        data["v373"] = {
            "active": True,
            "dashboard_restore": True,
            "kr_us_state_route_restored": bool(restored.get("state")),
            "coin_state_route_restored": bool(restored.get("coin")),
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

    restored = {
        "state": _restore_trimmed_route(core, "/api/state"),
        "coin": _restore_trimmed_route(core, "/api/coin/state"),
    }
    _install_health(core, restored)
    print(
        "NAMUH V373 DASHBOARD RESTORE active: "
        f"state={restored['state']} coin={restored['coin']} layout unchanged",
        flush=True,
    )
    return True
