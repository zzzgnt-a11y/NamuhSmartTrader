from __future__ import annotations

from datetime import datetime

C2_ENTRY_SCORE = 70.0
C3_ENTRY_SCORE = 75.0


def _blocked(q):
    blocked = bool(getattr(q, "event_blocked", False)) if q is not None else False
    try:
        blocked = blocked or any(
            bool(x.get("blocked"))
            for x in list(getattr(q, "events", []) or [])
            if isinstance(x, dict)
        )
    except Exception:
        pass
    return blocked


def apply(ns=None):
    """Final user overrides: C2 PM window + C2/C3 entry-score gates only."""
    import namuh_strategy123_patch
    import namuh_strategy23_fix

    # Keep the user's latest Condition 2 afternoon entry window.
    window = (13 * 60, 15 * 60)
    namuh_strategy123_patch.ENTRY2_PM = window
    namuh_strategy23_fix.ENTRY2_PM = window

    core = ns.get("core") if isinstance(ns, dict) else None
    if core is None or getattr(core, "_NAMUH_USER_ENTRY_SCORE_OVERRIDE", False):
        return
    core._NAMUH_USER_ENTRY_SCORE_OVERRIDE = True

    # Final candidate owner: preserve every existing C2 prerequisite, changing
    # only the score threshold from 72 to 70. C3 uses the existing overall AI
    # score as its score gate and requires 75 or more.
    old_candidate = core.candidate

    def candidate(*args, **kwargs):
        out = old_candidate(*args, **kwargs)
        if not isinstance(out, dict):
            return out
        market = str(args[1] if len(args) > 1 else kwargs.get("market", "")).upper()
        smart = bool(args[2] if len(args) > 2 else kwargs.get("smart", False))
        if market != "KR" or smart:
            return out

        q = args[0] if args else kwargs.get("q")
        c2 = out.get("condition2")
        if isinstance(c2, dict):
            score = float(out.get("condition2_score", c2.get("score", 0)) or 0)
            kospi = c2.get("kospi_1m") if isinstance(c2.get("kospi_1m"), dict) else {}
            monthly = c2.get("monthly_discount") if isinstance(c2.get("monthly_discount"), dict) else {}
            gate = bool(
                not _blocked(q)
                and score >= C2_ENTRY_SCORE
                and kospi.get("ready")
                and kospi.get("up")
                and monthly.get("ready")
                and monthly.get("pass")
            )
            c2["entry_score"] = C2_ENTRY_SCORE
            c2["gate"] = gate
            out["condition2"] = c2
            out["condition2_score"] = score
            out["condition2_gate_pass"] = gate

        c3 = out.get("condition3")
        if isinstance(c3, dict):
            score3 = float(out.get("score", 0) or 0)
            c3["score"] = score3
            c3["entry_score"] = C3_ENTRY_SCORE
            c3["score_gate"] = bool(score3 >= C3_ENTRY_SCORE)
            c3["gate"] = bool(c3.get("sector_top3") and c3["score_gate"])
            out["condition3"] = c3

        return out

    core.candidate = candidate

    # C3's all-market worker can reach the paper engine without going through
    # the visible candidate list. Guard the actual BUY as the final authority so
    # an attempted C3 order cannot bypass the 75-point requirement. C2 is also
    # checked again here so 70 is the single final threshold at execution time.
    old_buy = core.paper.buy

    def buy_guard(quote, qty, market, fx_rate, day_key, strategy="SCALP", entry_session=""):
        label = str(strategy or "")
        if str(market or "").upper() == "KR" and label in ("조건2", "조건3"):
            try:
                now = datetime.now(core.KST)
                cand = core.candidate(quote, "KR", False, now=now)
            except Exception as exc:
                print(f"NAMUH ENTRY SCORE BLOCK {label}: score unavailable {exc}", flush=True)
                return None

            if label == "조건2":
                score = float(cand.get("condition2_score", 0) or 0)
                gate = bool((cand.get("condition2") or {}).get("gate"))
                if score < C2_ENTRY_SCORE or not gate:
                    print(f"NAMUH ENTRY SCORE BLOCK 조건2 {getattr(quote, 'code', '')}: {score:.1f}/70", flush=True)
                    return None
            else:
                score = float(cand.get("score", 0) or 0)
                if score < C3_ENTRY_SCORE:
                    print(f"NAMUH ENTRY SCORE BLOCK 조건3 {getattr(quote, 'code', '')}: {score:.1f}/75", flush=True)
                    return None

        return old_buy(quote, qty, market, fx_rate, day_key, strategy=strategy, entry_session=entry_session)

    core.paper.buy = buy_guard
    print(
        "NAMUH USER ENTRY RULES active: C2>=70; C3>=75; C2 PM 13:00-15:00 KST",
        flush=True,
    )
