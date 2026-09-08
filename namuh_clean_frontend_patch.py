from __future__ import annotations

from pathlib import Path

from fastapi.responses import FileResponse

ROOT = Path(__file__).resolve().parent
_INSTALLED = False


def _front_route(app, path: str, endpoint, name: str):
    app.add_api_route(path, endpoint, methods=["GET"], include_in_schema=False, name=name)
    route = app.router.routes.pop()
    app.router.routes.insert(0, route)


def apply(ns=None):
    global _INSTALLED
    if _INSTALLED:
        return True
    core = ns.get("core") if isinstance(ns, dict) else None
    if core is None:
        return False

    home = ROOT / "static" / "rebuild-index.html"
    stock = ROOT / "static" / "rebuild-stock.html"
    if not home.exists() or not stock.exists():
        print("NAMUH CLEAN FRONTEND missing canonical templates", flush=True)
        return False

    app = core.app
    if getattr(app.state, "namuh_clean_frontend", False):
        _INSTALLED = True
        return True

    def clean_home():
        return FileResponse(home)

    def clean_stock(market: str, code: str):
        return FileResponse(stock)

    # FastAPI/Starlette resolves routes in list order. Put the clean routes at
    # the very front so legacy root/detail handlers and HTML patchers can no
    # longer win, while every existing API/static/coin/index route remains.
    _front_route(app, "/", clean_home, "namuh_clean_home")
    _front_route(app, "/stock/{market}/{code}", clean_stock, "namuh_clean_stock")
    app.state.namuh_clean_frontend = True
    _INSTALLED = True
    print("NAMUH CLEAN FRONTEND route override active", flush=True)
    return True
