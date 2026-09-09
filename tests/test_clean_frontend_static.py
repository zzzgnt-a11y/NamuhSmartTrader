from __future__ import annotations

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


class CurrentFrontendRegression(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.start = read("START_SITE.bat")
        cls.pc_runtime = read("runtime_server_pc.py")
        cls.runtime = read("runtime_server_v34.py")
        cls.loader = read("namuh_patch_loader.py")
        cls.sitecustomize = read("sitecustomize.py")
        cls.home = read("static/index.html")
        cls.app_js = read("static/app.js")
        cls.stock_js = read("static/stock.js")
        cls.coin_js = read("static/coin.js")
        cls.v364 = read("static/v364_main.js")
        cls.v365 = read("static/v365_market_ui_fix.js")

    def _assert_once(self):
        for rel in (
            "runtime_server_pc.py",
            "runtime_server_v34.py",
            "namuh_patch_loader.py",
            "static/index.html",
            "static/app.js",
            "static/stock.js",
            "static/coin.js",
            "static/v364_main.js",
            "static/v365_market_ui_fix.js",
        ):
            self.assertTrue((ROOT / rel).is_file(), rel)

        # PC startup must use the dedicated existing launcher, never removed clean runtime.
        self.assertIn("python runtime_server_pc.py", self.start)
        self.assertNotIn("runtime_server_clean.py", self.start)
        self.assertIn('runpy.run_module("runtime_server_v34", run_name="__main__")', self.pc_runtime)
        self.assertIn("uvicorn.run(", self.runtime)

        # PC launcher disables only the process-local emergency re-block and restores NHPLUG.
        self.assertIn("_namuh_emergency_disable_nhplug = lambda: None", self.pc_runtime)
        self.assertIn("importlib.reload(_nhplug)", self.pc_runtime)
        self.assertIn("_namuh_emergency_disable_nhplug()", self.sitecustomize)

        # Removed clean/rebuild frontend must not be loaded at runtime.
        self.assertNotIn("namuh_clean_frontend_patch.apply", self.loader)
        self.assertNotIn("runtime_server_clean.py", self.loader)

        # Preserve current main UI ownership and existing API wiring.
        for asset in ("/static/app.js", "/static/v34.js", "/static/v344.js"):
            self.assertIn(asset, self.home)
        self.assertIn("v364_main.js", self.sitecustomize)
        self.assertIn("v365_market_ui_fix.js", self.sitecustomize)

        for needle in (
            "/api/state?market=", "/api/budget", "/api/sector/",
            "candidateCard", "render", "openSector",
        ):
            self.assertIn(needle, self.app_js)

        for needle in (
            "/api/v344/stock/", "/api/v344/disclosures/",
            "/api/v344/investor-stock/", "renderScores", "renderLiveFlow",
        ):
            self.assertIn(needle, self.stock_js)

        for needle in (
            "/api/coin/settings", "/api/coin/state", "renderCoinTrades",
            "renderCoinCalendar", "candidateCard",
        ):
            self.assertIn(needle, self.coin_js)

        # Keep current trade/history UI additions intact.
        self.assertIn("STOCK TRADE HISTORY", self.v364)
        self.assertIn("data-f=\"BUY\"", self.v364)
        self.assertIn("data-f=\"SELL\"", self.v364)
        self.assertIn("v365-us", self.v365)

        ast.parse(self.pc_runtime)
        ast.parse(self.runtime)
        ast.parse(self.loader)
        ast.parse(self.sitecustomize)

    def test_current_frontend_invariants_5_consecutive(self):
        for cycle in range(5):
            with self.subTest(cycle=cycle + 1):
                self._assert_once()


if __name__ == "__main__":
    unittest.main()
