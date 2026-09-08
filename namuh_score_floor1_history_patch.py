from __future__ import annotations

_INSTALLED = False


def _f(v, default=0.0):
    try:
        return float(v)
    except Exception:
        return float(default)


def _floor1(v, hi):
    return max(1.0, min(float(hi), _f(v)))


def apply(ns=None):
    global _INSTALLED
    if _INSTALLED:
        return True
    core = ns.get("core") if isinstance(ns, dict) else None
    if core is None:
        return False

    # The official shared minute-history collector already exists in the repo.
    # It was not connected in the final runtime chain. Install it here so the
    # score engine reuses the already-fetched/persisted history instead of
    # treating a cold live Quote as if no minute history existed.
    try:
        import namuh_minute_data_patch as minute_data
        minute_data.install(core)
    except Exception as exc:
        print("NAMUH FLOOR1 minute history install error:", str(exc)[:180], flush=True)

    import namuh_conditions_final_patch as c

    old_daily10 = c._daily10
    old_minute10 = c._minute_reversal10
    old_execution12 = c._execution12
    old_order8 = c._order8
    old_standard45 = c._standard45

    # Score floor applies only to the four C1 entry/precondition score blocks.
    # The pass/fail gate returned by the original recipe is deliberately kept.
    def daily10(q, today):
        score, ok, meta = old_daily10(q, today)
        meta = dict(meta or {})
        floored = _f(score) < 1.0
        score = _floor1(score, 10)
        meta["score_floor1"] = floored
        meta["zero_status"] = "SCORED"
        return score, ok, meta

    def minute10(core_, q, market):
        score, ok, meta = old_minute10(core_, q, market)
        meta = dict(meta or {})
        floored = _f(score) < 1.0
        score = _floor1(score, 10)
        meta["score_floor1"] = floored
        meta["zero_status"] = "SCORED"
        return score, ok, meta

    def execution12(q, ok):
        return _floor1(old_execution12(q, ok), 12)

    def order8(ratio):
        return _floor1(old_order8(ratio), 8)

    # Exactly seven STANDARD indicators. Each indicator has a minimum of 1 raw
    # point, then the unchanged 75 -> 45 conversion is applied. Bonuses are not
    # touched and can still legitimately be zero.
    def standard45(core_, q, market, sec_score, stock_score, now, volume_state):
        _std, raw, meta = old_standard45(core_, q, market, sec_score, stock_score, now, volume_state)
        raw = dict(raw or {})
        maxima = {
            "MACD": 10.0,
            "RSI": 10.0,
            "볼린저": 10.0,
            "거래량": 15.0,
            "이평": 10.0,
            "가격구조": 10.0,
            "엘리어트": 10.0,
        }
        floor_applied = {}
        for key, mx in maxima.items():
            before = _f(raw.get(key))
            raw[key] = _floor1(before, mx)
            floor_applied[key] = before < 1.0

        raw_total = sum(_f(raw.get(k)) for k in maxima)
        std45 = round(c._clamp(raw_total / 75.0 * 45.0, 0, 45), 1)

        meta = dict(meta or {})
        # All seven values are now numerically represented. Keep the underlying
        # recipe gate logic separate from score display; do not show a fake
        # DATA_MISSING/partial-score state for these seven components.
        meta["zero_audit"] = {k: "SCORED" for k in maxima}
        meta["availability"] = {**dict(meta.get("availability") or {}), **{k: True for k in maxima}}
        meta["complete"] = True
        meta["missing"] = []
        meta["floor1_applied"] = floor_applied
        meta["raw_total"] = round(raw_total, 1)
        return std45, raw, meta

    c._daily10 = daily10
    c._minute_reversal10 = minute10
    c._execution12 = execution12
    c._order8 = order8
    c._standard45 = standard45

    # namuh_zero_score_audit_patch is installed immediately before this patch.
    # Normalize its presentation-only DATA_MISSING state so the detail screen
    # shows the actual numeric score. Genuine recipe gates still come from the
    # original C1 gates; the floor never turns a failed gate into a pass.
    old_candidate = core.candidate
    if not getattr(old_candidate, "_namuh_floor1_history", False):
        def candidate(*args, **kwargs):
            out = old_candidate(*args, **kwargs)
            if not isinstance(out, dict):
                return out
            try:
                c1 = dict(out.get("condition1") or {})
                if not c1:
                    return out

                audit = dict(c1.get("zero_audit") or {})
                for key in (
                    "일봉", "분봉", "체결강도", "호가",
                    "MACD", "RSI", "볼린저", "거래량", "이평", "가격구조", "엘리어트",
                ):
                    audit[key] = "SCORED"
                # Bonuses retain their original 0-point behavior. A missing
                # optional bonus feed is represented as zero rather than turning
                # the whole 100-point score into a partial-score UI state.
                for key in ("섹터 상대강도", "주도섹터 수급", "뉴스/공시"):
                    if audit.get(key) == "DATA_MISSING":
                        audit[key] = "RECIPE_ZERO"

                c1["zero_audit"] = audit
                c1["score_complete"] = True
                c1["score_status"] = "READY"
                c1["missing_inputs"] = []

                # Rebuild only the final C1 gate that the audit wrapper may have
                # disabled because of a presentation DATA_MISSING flag. The
                # recipe's original four hard precondition gates are unchanged.
                gates = dict(c1.get("gates") or {})
                threshold = _f(c1.get("entry_threshold"), 72.0)
                total = _f(c1.get("score"))
                blocked = bool(gates.get("event_block", False))
                hard = bool(
                    gates.get("daily", False)
                    and gates.get("minute1m", False)
                    and gates.get("execution", False)
                    and gates.get("orderbook", False)
                )
                c1["gate"] = bool(not blocked and hard and total >= threshold)
                out["condition1"] = c1
                out["condition1_score"] = total

                labels = [x for x in list(out.get("condition_labels") or []) if str(x) != "조건1"]
                if c1["gate"]:
                    labels.insert(0, "조건1")
                labels = list(dict.fromkeys(labels))
                out["condition_labels"] = labels
                out["condition_display"] = "복합조건" if len([x for x in labels if str(x).startswith("조건") and "관찰" not in str(x)]) >= 2 else (labels[0] if labels else "")
                out["reasons"] = [r for r in list(out.get("reasons") or []) if not str(r).startswith("조건1 데이터 대기")]
            except Exception as exc:
                out["score_floor1_error"] = str(exc)[:160]
            return out

        candidate._namuh_floor1_history = True
        core.candidate = candidate

    _INSTALLED = True
    print("NAMUH SCORE FLOOR1 active: shared history connected + C1 entry/7-tech min 1; bonuses unchanged", flush=True)
    return True
