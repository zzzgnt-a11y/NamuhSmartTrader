from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def ids(text: str) -> set[str]:
    return set(re.findall(r'\bid=["\']([^"\']+)["\']', text))


class CleanFrontendRegression(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.start = read("START_SITE.bat")
        cls.runtime = read("runtime_server_v34.py")
        cls.loader = read("namuh_patch_loader.py")
        cls.route_patch = read("namuh_clean_frontend_patch.py")
        cls.home = read("static/rebuild-index.html")
        cls.stock = read("static/rebuild-stock.html")
        cls.main_js = read("static/rebuild.js")
        cls.stock_js = read("static/rebuild-stock.js")
        cls.base_css = read("static/rebuild.css")
        cls.full_css = read("static/rebuild-full.css")

    def _assert_once(self):
        # Canonical files and entrypoints.
        for rel in (
            "runtime_server_v34.py",
            "runtime_server_clean.py",
            "namuh_clean_frontend_patch.py",
            "static/rebuild-index.html",
            "static/rebuild-stock.html",
            "static/rebuild.css",
            "static/rebuild-full.css",
            "static/rebuild.js",
            "static/rebuild-stock.js",
        ):
            self.assertTrue((ROOT / rel).is_file(), rel)

        # Local START_SITE and Render's existing runtime entry both lead to the clean UI.
        self.assertIn("python runtime_server_clean.py", self.start)
        self.assertNotIn("python app.py", self.start)
        self.assertIn("uvicorn.run(", self.runtime)
        self.assertIn("namuh_clean_frontend_patch", self.loader)
        self.assertGreater(self.loader.index("namuh_clean_frontend_patch"), self.loader.index("namuh_v374_coin_ledger_fix"))

        # Clean route override must win route order without deleting backend APIs.
        self.assertIn('app.router.routes.insert(0, route)', self.route_patch)
        self.assertIn('"/stock/{market}/{code}"', self.route_patch)
        self.assertIn('"/"', self.route_patch)
        self.assertIn('rebuild-index.html', self.route_patch)
        self.assertIn('rebuild-stock.html', self.route_patch)

        # Main page: search stays at the top and legacy owners are absent.
        self.assertIn('class="rb-top"', self.home)
        self.assertIn('id="stockSearch"', self.home)
        self.assertIn('id="searchResults"', self.home)
        self.assertIn('AI 점수 상위 종목', self.home)
        self.assertIn('코스피·코스닥 분석 결과 중 높은 점수 순 · 최대 5개', self.home)
        self.assertIn('id="budget"', self.home)
        self.assertIn('id="markets"', self.home)
        self.assertIn('id="sectors"', self.home)
        self.assertIn('id="smartList"', self.home)
        self.assertIn('id="positions"', self.home)
        self.assertIn('id="calendar"', self.home)
        self.assertIn('id="events"', self.home)
        self.assertNotIn('/static/app.js', self.home)
        self.assertNotIn('/static/v34.js', self.home)
        self.assertNotIn('/static/v344.js', self.home)
        self.assertNotIn('/static/v364_main.js', self.home)
        self.assertNotIn('/static/v365_market_ui_fix.js', self.home)

        # Search layout invariants: top/sticky, never reparented by JS.
        self.assertRegex(self.base_css, r'\.rb-top\{[^}]*position:sticky[^}]*top:0')
        self.assertNotIn('appendChild(stockSearch', self.main_js)
        self.assertNotIn('insertBefore(stockSearch', self.main_js)
        self.assertIn('/api/v34/search?market=', self.main_js)
        self.assertIn('/api/v34/track/', self.main_js)

        # Candidate order is score-descending and clipped to exactly five.
        self.assertIn('.slice(0,5)', self.main_js)
        self.assertRegex(self.main_js, r'sort\(\(a,b\).*num\(b\.score\).*num\(a\.score\)')
        self.assertIn('top5(s.scalp||[])', self.main_js)

        # Full dashboard functions remain present in the clean owner.
        for needle in (
            '/api/state?market=', '/api/budget', '/api/sector/',
            'renderMarkets', 'renderSectors', 'renderEvents', 'renderCalendar',
            'saveBudget', 'openSector', 'showDay',
        ):
            self.assertIn(needle, self.main_js)

        # Stock detail must be composition-first, not the previously confused hourly score board.
        self.assertIn('AI 점수 구성표', self.stock)
        self.assertNotIn('시간대별 AI 점수', self.stock)
        self.assertIn('id="aiTotal"', self.stock)
        self.assertIn('id="breakdown"', self.stock)
        self.assertIn('compositionEntries', self.stock_js)
        self.assertIn('a?.breakdown', self.stock_js)
        self.assertIn('/api/v344/stock/', self.stock_js)
        self.assertIn('/api/v344/disclosures/', self.stock_js)
        self.assertIn('/api/v344/investor-stock/', self.stock_js)
        self.assertNotIn('/static/stock.js', self.stock)
        self.assertNotIn('/static/v346.css', self.stock)

        # Required DOM ids used by the clean JS exist in the canonical HTML.
        home_ids = ids(self.home)
        stock_ids = ids(self.stock)
        for required in (
            'stockSearch','searchResults','modeLabel','equity','pnl','health','topSignal','session','updated',
            'currentBudget','budget','saveBudget','autoMax','topSector','fxNote','marketCaption','markets','sectors',
            'eventStatus','events','closedBoard','top5','smartColumn','smartList','heldCost','positions','prevMonth',
            'monthTitle','nextMonth','calendar','daySummary','dayDetail','sectorModal','sectorTitle','sectorSummary','sectorMembers'
        ):
            self.assertIn(required, home_ids, required)
        for required in (
            'backBtn','error','stockName','stockMeta','stockPrice','chartStatus','candle','aiTotal','breakdown','reasons',
            'flowGrid','flow20Status','flow20','events'
        ):
            self.assertIn(required, stock_ids, required)

        # Python syntax sanity for the new runtime pieces.
        ast.parse(self.route_patch)
        ast.parse(read('runtime_server_clean.py'))
        ast.parse(self.loader)

    def test_clean_frontend_invariants_1000_cycles(self):
        for cycle in range(1000):
            with self.subTest(cycle=cycle):
                self._assert_once()


if __name__ == '__main__':
    unittest.main()
