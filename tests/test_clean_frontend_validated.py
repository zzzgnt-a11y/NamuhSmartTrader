from __future__ import annotations

import ast
import random
import re
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def ids(text: str) -> set[str]:
    return set(re.findall(r'\bid=["\']([^"\']+)["\']', text))


def literal_dollar_ids(js: str) -> set[str]:
    return set(re.findall(r"\$\(['\"]([^'\"]+)['\"]\)", js))


def static_assets(html: str) -> set[str]:
    return set(re.findall(r'(?:src|href)=["\']/static/([^?"\']+)', html))


class CleanFrontendValidated(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runtime = read("runtime_server_v34.py")
        cls.loader = read("namuh_patch_loader.py")
        cls.route_patch = read("namuh_clean_frontend_patch.py")
        cls.home = read("static/rebuild-index.html")
        cls.stock = read("static/rebuild-stock.html")
        cls.main_js = read("static/rebuild.js")
        cls.stock_js = read("static/rebuild-stock.js")
        cls.base_css = read("static/rebuild.css")
        cls.full_css = read("static/rebuild-full.css")
        py_parts = []
        for path in ROOT.rglob("*.py"):
            try:
                rel = path.relative_to(ROOT)
            except ValueError:
                continue
            if rel.parts and rel.parts[0] == "tests":
                continue
            try:
                py_parts.append(path.read_text(encoding="utf-8"))
            except UnicodeDecodeError:
                pass
        cls.python_sources = "\n".join(py_parts)

    def _assert_invariants(self):
        # Canonical production entry and clean owner files.
        for rel in (
            "runtime_server_v34.py",
            "namuh_patch_loader.py",
            "namuh_clean_frontend_patch.py",
            "static/rebuild-index.html",
            "static/rebuild-stock.html",
            "static/rebuild.css",
            "static/rebuild-full.css",
            "static/rebuild.js",
            "static/rebuild-stock.js",
        ):
            self.assertTrue((ROOT / rel).is_file(), rel)

        # Render keeps using runtime_server_v34; clean override must load after v374.
        self.assertIn("uvicorn.run(", self.runtime)
        self.assertIn("namuh_v374_coin_ledger_fix", self.loader)
        self.assertIn("namuh_clean_frontend_patch", self.loader)
        self.assertGreater(
            self.loader.index("namuh_clean_frontend_patch"),
            self.loader.index("namuh_v374_coin_ledger_fix"),
        )

        # Clean routes are inserted at the front so legacy HTML owners cannot win.
        self.assertIn("app.router.routes.insert(0, route)", self.route_patch)
        self.assertIn('"/"', self.route_patch)
        self.assertIn('"/stock/{market}/{code}"', self.route_patch)
        self.assertIn("rebuild-index.html", self.route_patch)
        self.assertIn("rebuild-stock.html", self.route_patch)
        self.assertIn("namuh_clean_frontend", self.route_patch)

        # Search/header remains the single sticky top owner.
        self.assertIn('class="rb-top"', self.home)
        self.assertIn('id="stockSearch"', self.home)
        self.assertIn('id="searchResults"', self.home)
        self.assertRegex(self.base_css, r"\.rb-top\{[^}]*position:sticky[^}]*top:0")
        self.assertNotIn("appendChild(stockSearch", self.main_js)
        self.assertNotIn("insertBefore(stockSearch", self.main_js)

        # Legacy frontend scripts must not be injected into canonical clean pages.
        for legacy in (
            "/static/app.js",
            "/static/v34.js",
            "/static/v344.js",
            "/static/v364_main.js",
            "/static/v365_market_ui_fix.js",
        ):
            self.assertNotIn(legacy, self.home)
        self.assertNotIn("/static/stock.js", self.stock)
        self.assertNotIn("/static/v346.css", self.stock)

        # Every static asset referenced by canonical HTML must exist.
        for asset in static_assets(self.home) | static_assets(self.stock):
            self.assertTrue((ROOT / "static" / asset).is_file(), asset)

        # Whole-market search/on-demand tracking and guarded state refresh.
        self.assertIn("/api/v34/search?market=", self.main_js)
        self.assertIn("/api/v34/track/", self.main_js)
        self.assertIn("/api/state?market=", self.main_js)
        self.assertIn("AbortController", self.main_js)
        self.assertIn("if(busy)return;busy=true", self.main_js)
        self.assertIn("finally{busy=false}", self.main_js)

        # AI board is score-descending, capped to five, and still rendered after close.
        self.assertIn("function top5(rows)", self.main_js)
        self.assertIn("num(b.score)-num(a.score)", self.main_js)
        self.assertIn(".slice(0,5)", self.main_js)
        self.assertIn("fast=top5(s.scalp||[])", self.main_js)
        self.assertIn("html('top5',fast.length", self.main_js)
        self.assertIn("classList.toggle('hide',scan)", self.main_js)
        self.assertIn("AI 점수 상위 종목", self.home)
        self.assertIn("코스피·코스닥 분석 결과 중 높은 점수 순 · 최대 5개", self.home)

        # Dashboard features retained under the clean owner.
        for needle in (
            "/api/budget",
            "/api/sector/",
            "renderMarkets",
            "renderSectors",
            "renderEvents",
            "renderCalendar",
            "saveBudget",
            "openSector",
            "showDay",
        ):
            self.assertIn(needle, self.main_js)

        home_ids = ids(self.home)
        for required in (
            "stockSearch","searchResults","modeLabel","equity","pnl","health","topSignal","session","updated",
            "currentBudget","budget","saveBudget","autoMax","topSector","fxNote","marketCaption","markets","sectors",
            "eventStatus","events","closedBoard","top5","smartColumn","smartList","heldCost","positions","prevMonth",
            "monthTitle","nextMonth","calendar","daySummary","dayDetail","sectorModal","sectorTitle","sectorSummary","sectorMembers",
        ):
            self.assertIn(required, home_ids, required)
        self.assertTrue(literal_dollar_ids(self.main_js).issubset(home_ids), sorted(literal_dollar_ids(self.main_js) - home_ids))

        # Detail page: composition board only; requests are timeout/overlap guarded.
        self.assertIn("AI 점수 구성표", self.stock)
        self.assertNotIn("시간대별 AI 점수", self.stock)
        self.assertIn("compositionEntries", self.stock_js)
        self.assertIn("a?.breakdown", self.stock_js)
        self.assertIn("a?.components", self.stock_js)
        self.assertIn("if(busy)return;busy=true", self.stock_js)
        self.assertIn("AbortController", self.stock_js)
        self.assertIn("/api/v344/stock/", self.stock_js)
        self.assertIn("/api/v344/disclosures/", self.stock_js)
        self.assertIn("/api/v344/investor-stock/", self.stock_js)
        self.assertIn("setTimeout(loadEvents,150)", self.stock_js)
        self.assertIn("setTimeout(loadFlow20,350)", self.stock_js)
        self.assertIn("setInterval(()=>load(TF),30000)", self.stock_js)

        stock_ids = ids(self.stock)
        for required in (
            "backBtn","error","stockName","stockMeta","stockPrice","chartStatus","candle","aiTotal","breakdown","reasons",
            "flowGrid","flow20Status","flow20","events",
        ):
            self.assertIn(required, stock_ids, required)
        self.assertTrue(literal_dollar_ids(self.stock_js).issubset(stock_ids), sorted(literal_dollar_ids(self.stock_js) - stock_ids))

        # Frontend/backend contract sanity: every called API family must exist in Python source.
        for api in (
            "/api/state",
            "/api/budget",
            "/api/sector/",
            "/api/v34/search",
            "/api/v34/track/",
            "/api/v344/stock/",
            "/api/v344/disclosures/",
            "/api/v344/investor-stock/",
        ):
            self.assertIn(api, self.python_sources, api)

        # Syntax-level sanity.
        ast.parse(self.runtime)
        ast.parse(self.loader)
        ast.parse(self.route_patch)

    def test_static_invariants_1000_cycles(self):
        for cycle in range(1000):
            with self.subTest(cycle=cycle):
                self._assert_invariants()

    def test_top5_sort_property_10000_cases(self):
        rng = random.Random(20260909)
        for _ in range(10000):
            n = rng.randint(0, 50)
            rows = [
                {
                    "code": f"C{i:04d}",
                    "score": rng.uniform(-50, 150),
                    "priority_score": rng.uniform(-50, 150),
                }
                for i in range(n)
            ]
            got = sorted(
                rows,
                key=lambda x: (float(x["score"]), float(x["priority_score"])),
                reverse=True,
            )[:5]
            self.assertLessEqual(len(got), 5)
            for a, b in zip(got, got[1:]):
                self.assertGreaterEqual(
                    (a["score"], a["priority_score"]),
                    (b["score"], b["priority_score"]),
                )

    def test_route_override_executes_and_is_idempotent(self):
        tree = ast.parse(self.route_patch)
        selected = [
            node for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in {"_front_route", "apply"}
        ]
        code = compile(ast.Module(body=selected, type_ignores=[]), "namuh_clean_frontend_patch.py", "exec")

        class FakeFileResponse:
            def __init__(self, path):
                self.path = Path(path)

        class FakeRoute:
            def __init__(self, path, endpoint=None, name=None):
                self.path = path
                self.endpoint = endpoint
                self.name = name

        class FakeApp:
            def __init__(self):
                self.router = types.SimpleNamespace(routes=[FakeRoute("/"), FakeRoute("/stock/{market}/{code}")])
                self.state = types.SimpleNamespace()

            def add_api_route(self, path, endpoint, **kwargs):
                self.router.routes.append(FakeRoute(path, endpoint, kwargs.get("name")))

        env = {
            "ROOT": ROOT,
            "_INSTALLED": False,
            "FileResponse": FakeFileResponse,
        }
        exec(code, env)
        app = FakeApp()
        core = types.SimpleNamespace(app=app)
        self.assertTrue(env["apply"]({"core": core}))
        self.assertEqual(app.router.routes[0].path, "/stock/{market}/{code}")
        self.assertEqual(app.router.routes[1].path, "/")
        self.assertEqual(app.router.routes[0].name, "namuh_clean_stock")
        self.assertEqual(app.router.routes[1].name, "namuh_clean_home")
        self.assertTrue(app.state.namuh_clean_frontend)
        before = len(app.router.routes)
        self.assertTrue(env["apply"]({"core": core}))
        self.assertEqual(len(app.router.routes), before)
        home_response = app.router.routes[1].endpoint()
        stock_response = app.router.routes[0].endpoint("KR", "005930")
        self.assertEqual(home_response.path.name, "rebuild-index.html")
        self.assertEqual(stock_response.path.name, "rebuild-stock.html")


if __name__ == "__main__":
    unittest.main()
