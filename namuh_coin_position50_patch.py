from __future__ import annotations

_INSTALLED = False


def apply(ns):
    """Make each automatic Condition1/2 coin entry use 50% of effective coin budget.

    The final condition loop currently passes a 20% amount into coin_paper.buy().
    This late patch only adjusts automatic Condition1/2 buys, leaving manual/other
    strategy buys untouched. Available cash/budget remains the hard cap.
    """
    global _INSTALLED
    if _INSTALLED:
        return True

    core = ns.get("core") if isinstance(ns, dict) else None
    if core is None or getattr(core, "coin_paper", None) is None:
        return False

    old_buy = core.coin_paper.buy
    if getattr(old_buy, "_namuh_coin_position50", False):
        _INSTALLED = True
        return True

    def buy50(quote, krw_amount, strategy="COIN_SCALP"):
        strategy_name = str(strategy or "")
        if strategy_name in ("조건1", "조건2"):
            try:
                available = float(core._coin_available_budget() or 0)
                budget = float(core._coin_effective_budget() or 0)
                krw_amount = min(available, max(10000.0, budget * 0.50))
            except Exception:
                pass
        return old_buy(quote, krw_amount, strategy)

    buy50._namuh_coin_position50 = True
    core.coin_paper.buy = buy50
    core.COIN_ENTRY_POSITION_PCT = 50
    _INSTALLED = True
    print("NAMUH COIN POSITION SIZE active: 50% per Condition1/2 entry", flush=True)
    return True
