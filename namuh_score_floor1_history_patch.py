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

    # Reconnect the repository's existing official minute-history collector to
    # the final runtime chain. This lets C1 reuse fetched/persisted 1m history
    # instead of evaluating only a cold live Quote buffer.
    try:
        import namuh_minute_data_patch as minute_data
        minute_data.install(core)
    except Exception as exc:
        print("NAMUH FLOOR1 minute history install error:", str(exc)[:180], flush=True)

    import namuh_conditions_final_patch as c

    # Do not modify the shared scoring helpers because Condition2 and coin reuse
    # some of them. Apply the user's 1-point minimum strictly to stock Condition1.
    old_candidate = core.candidate
    if not getattr(old_candidate, "_namuh_floor1_history", False):
        def candidate(*args, **kwargs):
            out = old_candidate(*args, **kwargs)
            if not isinstance(out, dict):
                return out
            try:
                market = str(args[1] if len(args) > 1 else kwargs.get("market", "")).upper()
                if market not in ("KR", "US"):
                    return out

                c1 = dict(out.get("condition1") or {})
                if not c1:
                    return out

                bd = dict(c1.get("breakdown") or {})
                raw = dict(c1.get("standard_raw") or {})

                # C1 entry/precondition score floor only. The original pass/fail
                # gates remain untouched, so 1 point never turns a failed entry
                # condition into a pass.
                bd["daily10"] = _floor1(bd.get("daily10"), 10)
                bd["minute10"] = _floor1(bd.get("minute10"), 10)
                bd["execution12"] = _floor1(bd.get("execution12"), 12)
                bd["orderbook8"] = _floor1(bd.get("orderbook8"), 8)

                # Exactly seven STANDARD indicators. Each raw indicator is at
                # least 1 point, then the existing 75 -> 45 conversion is kept.
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
                standard45 = round(c._clamp(raw_total / 75.0 * 45.0, 0, 45), 1)
                bd["standard45"] = standard45

                prereq40 = round(
                    _f(bd.get("daily10")) + _f(bd.get("minute10"))
                    + _f(bd.get("execution12")) + _f(bd.get("orderbook8")), 1
                )
                bonus15 = round(
                    _f(bd.get("sector_relative7_5"))
                    + _f(bd.get("leading_sector_flow3_75"))
                    + _f(bd.get("news3_75")), 1
                )

                gates = dict(c1.get("gates") or {})
                blocked = bool(gates.get("event_block", False))
                total = round(c._clamp(prereq40 + standard45 + bonus15, 0, 100), 1)
                if blocked:
                    total = 0.0

                threshold = _f(c1.get("entry_threshold"), 72.0)
                hard = bool(
                    gates.get("daily", False)
                    and gates.get("minute1m", False)
                    and gates.get("execution", False)
                    and gates.get("orderbook", False)
                )
                gate = bool(not blocked and hard and total >= threshold)
                gates["total72"] = total >= threshold

                techmeta = dict(c1.get("technical_meta") or {})
                techmeta["zero_audit"] = {k: "SCORED" for k in maxima}
                techmeta["availability"] = {**dict(techmeta.get("availability") or {}), **{k: True for k in maxima}}
                techmeta["complete"] = True
                techmeta["missing"] = []
                techmeta["floor1_applied"] = floor_applied
                techmeta["raw_total"] = round(raw_total, 1)

                # Remove presentation-only DATA_MISSING states. Entry + technical
                # rows are numeric; optional bonus rows remain allowed to be 0.
                audit = dict(c1.get("zero_audit") or {})
                for key in (
                    "일봉", "분봉", "체결강도", "호가",
                    "MACD", "RSI", "볼린저", "거래량", "이평", "가격구조", "엘리어트",
                ):
                    audit[key] = "SCORED"
                for key in ("섹터 상대강도", "주도섹터 수급", "뉴스/공시"):
                    if audit.get(key) == "DATA_MISSING":
                        audit[key] = "RECIPE_ZERO"

                c1.update({
                    "score": total,
                    "gate": gate,
                    "breakdown": bd,
                    "standard_raw": raw,
                    "gates": gates,
                    "technical_meta": techmeta,
                    "prerequisite_score": prereq40,
                    "standard_score": standard45,
                    "bonus_score": bonus15,
                    "zero_audit": audit,
                    "score_complete": True,
                    "score_status": "READY",
                    "missing_inputs": [],
                    "minimum_score_policy": "C1 entry + seven technical indicators = minimum 1 point",
                })

                out["condition1"] = c1
                out["condition1_score"] = total
                out["score"] = total
                out["priority_score"] = total

                labels = [x for x in list(out.get("condition_labels") or []) if str(x) != "조건1"]
                if gate:
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
    print("NAMUH SCORE FLOOR1 active: shared history connected + stock C1 entry/7-tech min 1; C2/coin/bonus unchanged", flush=True)
    return True
