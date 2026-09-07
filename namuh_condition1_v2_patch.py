from __future__ import annotations

import time

_INSTALLED = False


def _f(v, default=0.0):
    try:
        return float(v)
    except Exception:
        return float(default)


def _clamp(v, lo=0.0, hi=100.0):
    return max(lo, min(hi, _f(v)))


def _blocked(q):
    blocked = bool(getattr(q, "event_blocked", False))
    try:
        blocked = blocked or any(bool(x.get("blocked")) for x in list(getattr(q, "events", []) or []) if isinstance(x, dict))
    except Exception:
        pass
    return blocked


def _minute20_from_ticks(q):
    """Pure 1-minute price-action score; no RSI/MACD duplication.

    Uses completed 1m buckets only:
      bullish candle 5 + higher close 5 + short breakout 5 + 3-close rise 5.
    """
    try:
        ticks = list(getattr(q, "tick_history", []) or [])
    except Exception:
        ticks = []
    buckets = {}
    for row in ticks:
        try:
            ts = float(row[0]); px = float(row[1])
        except Exception:
            continue
        if ts <= 0 or px <= 0:
            continue
        key = int(ts // 60)
        b = buckets.get(key)
        if b is None:
            buckets[key] = {"open": px, "high": px, "low": px, "close": px}
        else:
            b["high"] = max(float(b["high"]), px)
            b["low"] = min(float(b["low"]), px)
            b["close"] = px
    current = int(time.time() // 60)
    rows = [buckets[k] for k in sorted(buckets) if k < current]
    if len(rows) < 3:
        return 0.0, {"ready": False, "bars": len(rows), "reason": "완료 1분봉 3개 미만"}
    last = rows[-1]
    prev = rows[-2]
    pts = 0.0
    bull = _f(last.get("close")) > _f(last.get("open"))
    higher = _f(last.get("close")) > _f(prev.get("close"))
    prev_rows = rows[-4:-1] if len(rows) >= 4 else rows[:-1]
    prev_high = max((_f(x.get("high")) for x in prev_rows), default=0.0)
    breakout = prev_high > 0 and _f(last.get("close")) > prev_high
    closes = [_f(x.get("close")) for x in rows[-3:]]
    rising3 = len(closes) == 3 and closes[0] < closes[1] < closes[2]
    pts += 5.0 if bull else 0.0
    pts += 5.0 if higher else 0.0
    pts += 5.0 if breakout else 0.0
    pts += 5.0 if rising3 else 0.0
    return round(pts, 1), {
        "ready": True, "bars": len(rows), "bullish": bull, "higher_close": higher,
        "breakout": breakout, "rising3": rising3, "last_close": _f(last.get("close")),
        "prev_high": prev_high,
    }


def _leading_sector5(core, q, out, sector_rankmap):
    sector = core.sector_name(q, "KR")
    rank = None
    for k in ("sector_rank", "leading_sector_rank"):
        if out.get(k) is not None:
            try:
                rank = int(out.get(k)); break
            except Exception:
                pass
    if rank is None and isinstance(sector_rankmap, dict):
        try:
            rank = int(sector_rankmap.get(sector) or 999)
        except Exception:
            rank = 999
    if rank is None:
        rank = 999
    pts = 5.0 if rank == 1 else 4.0 if rank == 2 else 3.0 if rank == 3 else 2.0 if rank == 4 else 1.0 if rank == 5 else 0.0
    return pts, rank, sector


def _sector_inner_flow5(core, q):
    """Rank only money-flow intensity inside the same sector.

    (foreign + institution + program) / volume, so this is distinct from the
    leading-sector bonus and from execution strength.
    """
    sector = core.sector_name(q, "KR")
    rows = []
    for p in list(core.feed.quotes_for("KR").values()):
        if core.sector_name(p, "KR") != sector:
            continue
        vol = _f(getattr(p, "volume", 0))
        if vol <= 0:
            continue
        flow = _f(getattr(p, "foreign_net", 0)) + _f(getattr(p, "institution_net", 0)) + _f(getattr(p, "program_net", 0))
        rows.append((str(getattr(p, "code", "")), flow / vol))
    if not rows:
        return 0.0, 999, 0
    rows.sort(key=lambda x: x[1], reverse=True)
    rank = next((i for i, x in enumerate(rows, 1) if x[0] == str(getattr(q, "code", ""))), 999)
    pts = 5.0 if rank == 1 else 4.5 if rank == 2 else 4.0 if rank == 3 else 3.5 if rank == 4 else 3.0 if rank == 5 else 2.5 if rank == 6 else 2.0 if rank == 7 else 1.5 if rank == 8 else 1.0 if rank == 9 else 0.5 if rank == 10 else 0.0
    return pts, rank, len(rows)


def apply(ns):
    global _INSTALLED
    if _INSTALLED:
        return True
    core = ns.get("core") if isinstance(ns, dict) else None
    if core is None:
        return False

    old_candidate = core.candidate

    def candidate(q, market, smart=False, secmap=None, stockmap=None, leadermap=None, sector_rankmap=None, now=None):
        out = old_candidate(q, market, smart, secmap, stockmap, leadermap, sector_rankmap, now)
        if smart or not isinstance(out, dict) or str(market or "").upper() != "KR":
            return out

        comps = dict(out.get("score_components") or {})
        daily20 = round(_clamp(comps.get("daily20", 0), 0, 20), 1)
        minute20, minute_meta = _minute20_from_ticks(q)

        try:
            import namuh_execution_exit_patch as rules
            strength = _f(getattr(q, "execution_strength", 0))
            execution20 = round(_clamp(rules._execution_points(strength), 0, 20), 1)
            exec_ok, exec_reason = rules.execution_gate(q, time.time())
        except Exception:
            strength = _f(getattr(q, "execution_strength", 0))
            execution20 = round(_clamp(comps.get("execution20", 0), 0, 20), 1)
            exec_ok = bool(out.get("execution_gate_pass", False))
            exec_reason = str(out.get("execution_gate_reason") or "체결강도 확인")

        tech20 = out.get("technical_score")
        if tech20 is None:
            tech20 = comps.get("technical20", 0)
        technical25 = round(_clamp(_f(tech20) / 20.0 * 25.0, 0, 25), 1)

        leading5, sector_rank, sector = _leading_sector5(core, q, out, sector_rankmap)
        inner5, inner_rank, peer_count = _sector_inner_flow5(core, q)
        news5 = round(_clamp(out.get("fresh_event_points", comps.get("news5", 0)), 0, 5), 1)

        entry60 = round(daily20 + minute20 + execution20, 1)
        confirm25 = technical25
        bonus15 = round(leading5 + inner5 + news5, 1)
        total = round(_clamp(entry60 + confirm25 + bonus15, 0, 100), 1)

        daily_gate = daily20 >= 8.0
        minute_gate = bool(minute_meta.get("ready")) and minute20 >= 10.0
        technical_gate = technical25 >= 12.5
        blocked = _blocked(q)
        gate = bool(not blocked and total >= 72.0 and daily_gate and minute_gate and exec_ok and technical_gate)
        if blocked:
            total = 0.0

        breakdown = {
            "daily20": daily20,
            "minute20": minute20,
            "execution20": execution20,
            "technical25": technical25,
            "leading_sector5": leading5,
            "sector_inner_flow5": inner5,
            "news5": news5,
        }
        gates = {
            "daily": daily_gate,
            "minute1m": minute_gate,
            "execution": bool(exec_ok),
            "technical": technical_gate,
            "event_block": blocked,
            "total72": total >= 72.0,
        }

        out["score"] = total
        out["priority_score"] = total
        out["score_model"] = "C1_ENTRY60_CONFIRM25_BONUS15"
        out["entry_gate_pass"] = gate
        out["daily_gate_pass"] = daily_gate
        out["minute_gate_pass"] = minute_gate
        out["execution_gate_pass"] = bool(exec_ok)
        out["execution_gate_reason"] = str(exec_reason or "")
        out["technical_gate_pass"] = technical_gate
        comps.update(breakdown)
        out["score_components"] = comps
        out["condition1"] = {
            "label": "조건1", "score": total, "gate": gate, "entry_threshold": 72.0,
            "entry_score": entry60, "confirmation_score": confirm25, "bonus_score": bonus15,
            "breakdown": breakdown, "gates": gates,
            "minute_meta": minute_meta,
            "execution_strength": strength, "execution_reason": str(exec_reason or ""),
            "sector": sector, "leading_sector_rank": sector_rank,
            "sector_inner_flow_rank": inner_rank, "sector_peer_count": peer_count,
            "model": "일봉20 + 1분봉20 + 체결강도20 + 기술25 + 주도섹터5 + 섹터내수급5 + 공시/뉴스5",
        }
        labels = [x for x in list(out.get("condition_labels") or []) if str(x) not in ("조건1",)]
        if gate:
            labels.insert(0, "조건1")
        out["condition_labels"] = list(dict.fromkeys(labels))
        out["condition_display"] = "복합조건" if len([x for x in out["condition_labels"] if str(x).startswith("조건") and "관찰" not in str(x)]) >= 2 else (out["condition_labels"][0] if out["condition_labels"] else "")

        reasons = [r for r in list(out.get("reasons") or []) if not str(r).startswith("조건1 V2")]
        reasons.insert(0, f"조건1 V2 {total:.1f}/100 · 진입 {entry60:.1f}/60 → 기술확정 {confirm25:.1f}/25 → 추가가점 {bonus15:.1f}/15")
        reasons.insert(1, f"일봉 {daily20:.1f}/20 · 1분봉 {minute20:.1f}/20 · 체결강도 {execution20:.1f}/20 ({exec_reason})")
        reasons.insert(2, f"기술종합 {technical25:.1f}/25 · 주도섹터 {leading5:.1f}/5 · 섹터내수급 {inner5:.1f}/5 · 공시/뉴스 {news5:.1f}/5")
        out["reasons"] = reasons
        return out

    core.candidate = candidate

    old_detail = core.stock_detail
    def stock_detail(market, code, timeframe="1d", *args, **kwargs):
        d = dict(old_detail(market, code, timeframe, *args, **kwargs))
        m = str(market or "").upper()
        c = str(code or "").upper()
        row = None
        try:
            for x in list((getattr(core, "_NAMUH_ALL_SCORES", {}) or {}).get(m, []) or []):
                if str(x.get("code") or "").upper() == c:
                    row = x; break
        except Exception:
            row = None
        if isinstance(row, dict):
            d["strategy_conditions"] = {
                "condition1": row.get("condition1") or {},
                "condition2": row.get("condition2") or {},
                "condition3": row.get("condition3") or {},
                "condition2_score": row.get("condition2_score"),
                "condition_labels": row.get("condition_labels") or [],
                "condition_display": row.get("condition_display") or "",
            }
        return d
    core.stock_detail = stock_detail

    old_health = core.health_payload
    def health():
        d = dict(old_health())
        d["condition1_model"] = {
            "name": "ENTRY60_CONFIRM25_BONUS15",
            "components": {"daily":20,"minute1m":20,"execution":20,"technical":25,"leading_sector":5,"sector_inner_flow":5,"news_disclosure":5},
            "hard_gates": {"daily_min":8,"minute1m_min":10,"execution":"existing interlock","technical_min":12.5,"total_min":72,"negative_event_block":True},
        }
        return d
    core.health_payload = health

    _INSTALLED = True
    print("NAMUH CONDITION1 V2 active: daily20 + 1m20 + exec20 -> technical25 -> sector/news bonus15; total>=72", flush=True)
    return True
