from __future__ import annotations

from pathlib import Path
import re

_INSTALLED = False


def apply(ns: dict) -> bool:
    global _INSTALLED
    if _INSTALLED:
        return True
    core = ns.get('core')
    if core is None:
        return False

    # Restore official shared intraday history so stock detail can calculate
    # 1m/3m/5m/20m scores even after a deploy or after the cash session closes.
    try:
        import namuh_minute_data_patch
        namuh_minute_data_patch.install(core)
    except Exception as exc:
        print('NAMUH DETAIL minute-data install error:', str(exc)[:180], flush=True)

    # The chart endpoint used to synchronously fetch the same 3-month disclosure
    # history that stock.js already fetches in a separate request. Remove that
    # duplicate network wait from the chart/score response path.
    try:
        import v344_features as v344

        def stock_payload_fast(market: str, code: str, timeframe: str, days: int = 60) -> dict:
            market2 = 'US' if str(market).upper() == 'US' else 'KR'
            code2 = str(code or '').upper().strip()
            tf = str(timeframe or '1d').lower()
            q = v344._apply_stock_meta(market2, code2)
            try:
                d = dict(core.stock_detail(market2, code2, timeframe=tf))
            except Exception:
                d = {
                    'market': market2, 'code': code2, 'name': q.name or code2,
                    'sector': q.sector or '', 'price': v344._n(getattr(q, 'price', 0)),
                    'scores': {}, 'analysis': None, 'flow': {}, 'events': [],
                }
            d['name'] = q.name or d.get('name') or code2
            d['sector'] = q.sector or d.get('sector') or ''
            if market2 == 'KR' and v344._n(d.get('price')) <= 0:
                nq = v344._naver_kr_quote(code2)
                if nq.get('price'):
                    d['price'] = nq['price']
                    d['price_display_source'] = nq.get('source')
                    if nq.get('name') and (not d.get('name') or d.get('name') == code2):
                        d['name'] = nq['name']
            if tf in ('1d', 'd', 'day', '일봉'):
                bars, source = v344._daily_bars(market2, code2, days)
                d['bars'] = bars
                d['chart_source'] = source
                d['chart_days'] = len(bars)
                d['default_timeframe'] = '1d'
                d['chart_last_date'] = bars[-1]['time'] if bars else ''
                d['chart_expected_date'] = v344._expected_trade_date(market2)
                d['chart_regular_session_only'] = True
                if v344._n(d.get('price')) <= 0 and bars:
                    d['price'] = bars[-1]['close']
                    d['price_display_source'] = '최근 공식 종가'
                else:
                    d.setdefault('price_display_source', '현재가')
            # Events load independently through /api/v344/disclosures/... so the
            # first chart response is not blocked by DART/SEC/Naver history calls.
            d['events'] = []
            d['event_history_source'] = '별도 비동기 로딩'
            d['event_history_status'] = ''
            return d

        v344._stock_payload = stock_payload_fast
    except Exception as exc:
        print('NAMUH DETAIL fast-payload error:', str(exc)[:180], flush=True)

    # Keep chart/detail responsive without hammering the same strategy endpoint.
    # Main state is 5 seconds, so matching that cadence avoids duplicate 2-second
    # recomputation while still feeling live to the user.
    try:
        p = Path(__file__).resolve().parent / 'static' / 'stock.js'
        text = p.read_text(encoding='utf-8')
        text = text.replace(
            "loadStock('1d');loadInvestorFlow();loadStockEvents();setInterval(()=>loadStock(TF),15000);setInterval(loadInvestorFlow,30000);setInterval(loadStockEvents,120000);",
            "loadStock('1d');setTimeout(loadInvestorFlow,250);setTimeout(loadStockEvents,400);setInterval(()=>loadStock(TF),5000);setInterval(loadInvestorFlow,30000);setInterval(loadStockEvents,120000);"
        )
        text = re.sub(r"setInterval\(\(\)=>loadStock\(TF\),\s*(?:15000|3000|2000|5000)\)", "setInterval(()=>loadStock(TF),5000)", text)
        p.write_text(text, encoding='utf-8')
    except Exception as exc:
        print('NAMUH DETAIL stock.js speed error:', str(exc)[:180], flush=True)

    _INSTALLED = True
    print('NAMUH STOCK DETAIL FIX active: timeframe scores restored, chart prioritized, refresh=5s', flush=True)
    return True
