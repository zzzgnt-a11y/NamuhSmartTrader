from __future__ import annotations

TARGET_STOCK_ASSET_KRW = 2_000_000


def apply(ns):
    core = ns.get('core')
    if core is None or getattr(core, '_NAMUH_STOCK_ASSET_2M_APPLIED', False):
        return
    core._NAMUH_STOCK_ASSET_2M_APPLIED = True

    paper = core.paper
    legacy_runtime_base = int(getattr(paper, 'initial_cash_krw', 1_000_000) or 1_000_000)
    paper.initial_cash_krw = TARGET_STOCK_ASSET_KRW

    original_payload = core._paper_payload
    original_restore = core._restore_paper

    def paper_payload_2m():
        d = dict(original_payload())
        d['initial_cash_krw'] = TARGET_STOCK_ASSET_KRW
        return d

    def restore_paper_2m():
        raw = core.store.load_json('paper_account', None)
        paper.initial_cash_krw = TARGET_STOCK_ASSET_KRW
        if not isinstance(raw, dict):
            paper.cash_krw = float(TARGET_STOCK_ASSET_KRW)

        original_restore()

        if isinstance(raw, dict):
            try:
                stored_base = int(raw.get('initial_cash_krw') or legacy_runtime_base)
            except Exception:
                stored_base = legacy_runtime_base
            delta = TARGET_STOCK_ASSET_KRW - stored_base
            if delta:
                # Preserve existing positions/trade PnL while moving the account
                # base to 2M. If downsizing would make cash negative, stop at 0;
                # the 2M budget cap prevents any additional buying until holdings
                # fall back under the new limit.
                paper.cash_krw = max(0.0, float(paper.cash_krw) + float(delta))

        paper.initial_cash_krw = TARGET_STOCK_ASSET_KRW
        paper.auto_max_if_unset = True
        try:
            day = core.trading_day_key('KR')
            paper.budget_day = day
            paper.explicit_budget_krw = TARGET_STOCK_ASSET_KRW
        except Exception:
            pass

        core._persist_paper()
        try:
            equity = float(paper.equity_krw())
            held = float(paper.held_cost_krw())
        except Exception:
            equity, held = 0.0, 0.0
        print(
            f'NAMUH STOCK ASSET: base=2000000 cash={paper.cash_krw:.0f} '
            f'equity={equity:.0f} held={held:.0f} budget=2000000',
            flush=True,
        )

    core._paper_payload = paper_payload_2m
    core._restore_paper = restore_paper_2m
    print('NAMUH STOCK ASSET PATCH armed: KR stock asset/budget = 2,000,000 KRW', flush=True)
