from __future__ import annotations

C1_ENTRY_SCORE = 75.0


def _score_of(row):
    try:
        c1 = row.get("condition1") or {}
        return float(c1.get("score") if c1.get("score") is not None else row.get("score") or 0)
    except Exception:
        return 0.0


def _apply_gate(row):
    if not isinstance(row, dict):
        return row
    c1 = dict(row.get("condition1") or {})
    score = _score_of(row)
    c1["score"] = score
    c1["entry_threshold"] = C1_ENTRY_SCORE
    # Preserve every pre-existing gate (execution/event/time-independent checks)
    # and only tighten the score requirement from the legacy 72 to 75.
    c1["gate"] = bool(c1.get("gate", False) and score >= C1_ENTRY_SCORE)
    row["condition1"] = c1
    row["condition1_gate_pass"] = bool(c1["gate"])

    labels = [str(x) for x in list(row.get("condition_labels") or [])]
    labels = [x for x in labels if x != "조건1"]
    if c1["gate"]:
        labels.insert(0, "조건1")
    row["condition_labels"] = labels
    if "condition_display" in row:
        row["condition_display"] = "복합조건" if len(labels) > 1 else (labels[0] if labels else "")
    return row


def apply(ns):
    core = ns.get("core") if isinstance(ns, dict) else None
    if core is None or getattr(core, "_NAMUH_C1_75_APPLIED", False):
        return
    core._NAMUH_C1_75_APPLIED = True

    old_candidate = core.candidate

    def candidate(q, market, smart=False, secmap=None, stockmap=None, leadermap=None, sector_rankmap=None, now=None):
        out = old_candidate(q, market, smart, secmap, stockmap, leadermap, sector_rankmap, now)
        if smart or not isinstance(out, dict) or str(market or "").upper() not in ("KR", "US"):
            return out
        return _apply_gate(out)

    core.candidate = candidate

    old_trade = core.trade_scalp

    def trade_scalp(market, candidates, now=None):
        m = str(market or "").upper()
        if m not in ("KR", "US"):
            return old_trade(market, candidates, now)
        fixed = []
        for row in list(candidates or []):
            if isinstance(row, dict):
                row = _apply_gate(dict(row))
            fixed.append(row)
        return old_trade(market, fixed, now)

    core.trade_scalp = trade_scalp

    try:
        old_health = core.health_payload

        def health():
            d = dict(old_health())
            scores = dict(d.get("condition_entry_scores") or {})
            scores["condition1"] = C1_ENTRY_SCORE
            scores["condition1_markets"] = ["KR", "US"]
            d["condition_entry_scores"] = scores
            return d

        core.health_payload = health
    except Exception:
        pass

    print("NAMUH CONDITION1 ENTRY SCORE active: KR/US C1>=75", flush=True)
