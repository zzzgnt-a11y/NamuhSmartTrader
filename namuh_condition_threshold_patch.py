from __future__ import annotations

C2_ENTRY_SCORE = 70.0
C3_ENTRY_SCORE = 75.0


def apply(ns):
    core = ns.get("core") if isinstance(ns, dict) else None
    if core is None or getattr(core, "_NAMUH_CONDITION_THRESHOLD_APPLIED", False):
        return
    core._NAMUH_CONDITION_THRESHOLD_APPLIED = True

    old_candidate = core.candidate

    def candidate(q, market, smart=False, secmap=None, stockmap=None, leadermap=None, sector_rankmap=None, now=None):
        out = old_candidate(q, market, smart, secmap, stockmap, leadermap, sector_rankmap, now)
        if smart or not isinstance(out, dict) or str(market or "").upper() != "KR":
            return out

        c2 = dict(out.get("condition2") or {})
        try:
            score2 = float(c2.get("score") if c2.get("score") is not None else out.get("condition2_score") or 0)
        except Exception:
            score2 = 0.0
        kospi = dict(c2.get("kospi_1m") or {})
        monthly = dict(c2.get("monthly_discount") or {})
        blocked = bool(getattr(q, "event_blocked", False))
        try:
            blocked = blocked or any(bool(e.get("blocked")) for e in list(getattr(q, "events", []) or []) if isinstance(e, dict))
        except Exception:
            pass
        c2_gate = bool(
            not blocked
            and score2 >= C2_ENTRY_SCORE
            and kospi.get("ready")
            and kospi.get("up")
            and monthly.get("ready")
            and monthly.get("pass")
        )
        c2["gate"] = c2_gate
        c2["entry_threshold"] = C2_ENTRY_SCORE
        out["condition2"] = c2
        out["condition2_score"] = score2
        out["condition2_gate_pass"] = c2_gate

        c3 = dict(out.get("condition3") or {})
        try:
            score3 = float(out.get("score") or 0)
        except Exception:
            score3 = 0.0
        c3["score"] = score3
        c3["entry_threshold"] = C3_ENTRY_SCORE
        c3["score_gate"] = bool(score3 >= C3_ENTRY_SCORE)
        out["condition3"] = c3
        return out

    core.candidate = candidate

    old_buy = core.paper.buy

    def buy(*args, **kwargs):
        q = args[0] if args else kwargs.get("q")
        market = str(args[2] if len(args) > 2 else kwargs.get("market", "")).upper()
        strategy = str(kwargs.get("strategy") or "")
        if market == "KR" and strategy == "조건3":
            code = str(getattr(q, "code", "") or "")
            score = None
            rows = list((getattr(core, "_NAMUH_ALL_SCORES", {}) or {}).get("KR", []) or [])
            for row in rows:
                if str(row.get("code") or "") == code:
                    try:
                        score = float(row.get("score") or 0)
                    except Exception:
                        score = None
                    break
            if score is None or score < C3_ENTRY_SCORE:
                print(f"CONDITION3 ENTRY BLOCK {code} score={score} threshold={C3_ENTRY_SCORE:.0f}", flush=True)
                return None
        return old_buy(*args, **kwargs)

    core.paper.buy = buy

    old_health = core.health_payload

    def health():
        d = dict(old_health())
        d["condition_entry_scores"] = {
            "condition2": C2_ENTRY_SCORE,
            "condition3": C3_ENTRY_SCORE,
            "condition3_score_source": "KR all-score current AI score; unavailable blocks entry",
        }
        return d

    core.health_payload = health
    print("NAMUH CONDITION ENTRY SCORE active: C2>=70 / C3>=75", flush=True)

    # Final requested feature bundle. Installed here because this module is
    # already the last runtime owner in sitecustomize.py.
    try:
        import minute_bar_persistence
        minute_bar_persistence._MAX_BARS = 60
        import namuh_minute_data_patch
        namuh_minute_data_patch.install(core)
        import namuh_final_requests_patch
        namuh_final_requests_patch.apply(ns)
    except Exception as exc:
        print("NAMUH FINAL REQUEST BUNDLE ERROR:", str(exc)[:220], flush=True)

    # Emergency UI restore: keep the backend/data/strategy changes above, but
    # remove only the v360 frontend overrides so the original site UI remains
    # the runtime owner.  This deliberately does not touch trading logic.
    try:
        import re
        from pathlib import Path

        for rel, script in (
            ("static/index.html", "v360_final.js"),
            ("static/stock.html", "stock-v360.js"),
            ("static/coin.html", "coin-v360.js"),
        ):
            p = Path(rel)
            if not p.exists():
                continue
            text = p.read_text(encoding="utf-8")
            restored = re.sub(
                rf"\s*<script\b[^>]*\bsrc=[\"'][^\"']*{re.escape(script)}[^\"']*[\"'][^>]*>\s*</script>\s*",
                "\n",
                text,
                flags=re.I,
            )
            if restored != text:
                p.write_text(restored, encoding="utf-8")

        p = Path("static/stock.js")
        if p.exists():
            text = p.read_text(encoding="utf-8")
            text = text.replace(
                "Math.floor((TF==='1d'?42:(TF==='1m'?60:30))/zoom)",
                "Math.floor((TF==='1d'?42:55)/zoom)",
            )
            text = text.replace(
                "function shortDate(v){const s=String(v||'').replace(/\\D/g,'');if(TF!=='1d'&&s.length>=12)return `${s.slice(8,10)}:${s.slice(10,12)}`;return s.length>=8?`${s.slice(4,6)}/${s.slice(6,8)}`:String(v||'')}",
                "function shortDate(v){const s=String(v||'').replace(/\\D/g,'');return s.length>=8?`${s.slice(4,6)}/${s.slice(6,8)}`:String(v||'')}",
            )
            p.write_text(text, encoding="utf-8")
        print("NAMUH SITE UI RESTORE active: v360 frontend overrides removed", flush=True)
    except Exception as exc:
        print("NAMUH SITE UI RESTORE ERROR:", str(exc)[:220], flush=True)
