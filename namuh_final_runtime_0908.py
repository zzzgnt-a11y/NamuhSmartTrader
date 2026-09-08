from __future__ import annotations

import re
import threading
import time
from pathlib import Path
from datetime import datetime

_INSTALLED = False
_AI_LOCK = threading.RLock()
_AI_HISTORY = {"KR": [], "US": []}
_AI_THREAD_STARTED = False
ROOT = Path(__file__).resolve().parent


def _f(v, default=0.0):
    try:
        return float(v)
    except Exception:
        return float(default)


def _clamp(v, lo=0.0, hi=100.0):
    return max(float(lo), min(float(hi), _f(v)))


def _market_now(core, market):
    now = datetime.now(core.KST)
    if str(market).upper() == "US":
        try:
            from zoneinfo import ZoneInfo
            return now.astimezone(ZoneInfo("America/New_York"))
        except Exception:
            return now
    return now


def _daily10_authoritative(core, q, market):
    try:
        import namuh_conditions_final_patch as rules
        now = _market_now(core, market)
        today = now.strftime("%Y%m%d")
        _, ok, meta = rules._daily10(q, today)
        return (10.0 if ok else 1.0), bool(ok), dict(meta or {})
    except Exception as exc:
        return 1.0, False, {"ready": False, "error": str(exc)[:160]}


def _recalc_c1_total(out, c1):
    bd = dict(c1.get("breakdown") or {})
    gates = dict(c1.get("gates") or {})
    prereq = round(
        _f(bd.get("daily10")) + _f(bd.get("minute10")) +
        _f(bd.get("execution12")) + _f(bd.get("orderbook8")), 1
    )
    std45 = _f(c1.get("standard_score"), _f(bd.get("standard45")))
    bonus = _f(c1.get("bonus_score"))
    if bonus == 0:
        bonus = (
            _f(bd.get("sector_relative7_5")) +
            _f(bd.get("leading_sector_flow3_75")) +
            _f(bd.get("news3_75"))
        )
    bonus = round(bonus, 2)
    blocked = bool(gates.get("event_block", False))
    total = round(_clamp(prereq + std45 + bonus, 0, 100), 1)
    if blocked:
        total = 0.0
    threshold = _f(c1.get("entry_threshold"), 75.0)
    hard = bool(
        gates.get("daily") and gates.get("minute1m") and
        gates.get("execution") and gates.get("orderbook")
    )
    gate = bool(not blocked and hard and total >= threshold)
    gates["total75"] = total >= 75.0
    gates["total_threshold"] = total >= threshold
    c1.update({
        "score": total,
        "gate": gate,
        "breakdown": bd,
        "gates": gates,
        "prerequisite_score": prereq,
        "standard_score": round(std45, 1),
        "bonus_score": bonus,
        "entry_threshold": threshold,
        "score_consistency_owner": "final_runtime_0908",
    })
    out["condition1"] = c1
    out["condition1_score"] = total
    out["score"] = total
    out["priority_score"] = total
    return c1


def _install_daily_fix(core):
    old_candidate = core.candidate
    if getattr(old_candidate, "_namuh_daily_authoritative", False):
        return

    def candidate(*args, **kwargs):
        out = old_candidate(*args, **kwargs)
        if not isinstance(out, dict):
            return out
        try:
            q = args[0] if args else kwargs.get("q")
            market = str(args[1] if len(args) > 1 else kwargs.get("market", "")).upper()
            smart = bool(args[2] if len(args) > 2 else kwargs.get("smart", False))
            if q is None or smart or market not in ("KR", "US"):
                return out
            c1 = dict(out.get("condition1") or {})
            if not c1:
                return out
            score, ok, meta = _daily10_authoritative(core, q, market)
            bd = dict(c1.get("breakdown") or {})
            gates = dict(c1.get("gates") or {})
            bd["daily10"] = score
            gates["daily"] = ok
            c1["breakdown"] = bd
            c1["gates"] = gates
            c1["daily_meta"] = meta
            c1["daily_score_source"] = "official completed daily + live price"
            _recalc_c1_total(out, c1)
            labels = [x for x in list(out.get("condition_labels") or []) if str(x) != "조건1"]
            if out["condition1"].get("gate"):
                labels.insert(0, "조건1")
            out["condition_labels"] = list(dict.fromkeys(labels))
            out["condition_display"] = (
                "복합조건" if len([x for x in out["condition_labels"] if str(x).startswith("조건")]) > 1
                else (out["condition_labels"][0] if out["condition_labels"] else "")
            )
        except Exception as exc:
            out["daily_authoritative_error"] = str(exc)[:220]
        return out

    candidate._namuh_daily_authoritative = True
    core.candidate = candidate


def _iter_dicts(v):
    if isinstance(v, dict):
        yield v
        for x in v.values():
            yield from _iter_dicts(x)
    elif isinstance(v, list):
        for x in v:
            yield from _iter_dicts(x)


def _install_investor_priority(core):
    feed = core.feed
    from nhfeed import num, normalize_date

    def apply_investor(code, data):
        rows = []
        for obj in _iter_dicts(data):
            if not isinstance(obj, dict):
                continue
            if any(k in obj for k in (
                "frgn_ntby_qty", "invest", "gigwan", "orgn_ntby_qty",
                "person", "prsn_ntby_qty", "program", "prgm_ntby_qty"
            )):
                rows.append(obj)
        parsed = {}
        for r in rows:
            d = normalize_date(
                r.get("bsop_date1") or r.get("bsop_date2") or r.get("bsop_date")
                or r.get("stck_bsop_date") or r.get("trade_date") or r.get("date")
            )
            if not d:
                continue
            f = num(r.get("frgn_ntby_qty") if r.get("frgn_ntby_qty") not in (None, "") else r.get("invest"))
            i = num(r.get("gigwan") if r.get("gigwan") not in (None, "") else r.get("orgn_ntby_qty"))
            pe = num(r.get("person") if r.get("person") not in (None, "") else r.get("prsn_ntby_qty"))
            pg = num(r.get("program") if r.get("program") not in (None, "") else r.get("prgm_ntby_qty"))
            parsed[d] = {"date": d, "foreign": f, "institution": i, "person": pe, "program": pg}
        if not parsed:
            old = getattr(apply_investor, "_old", None)
            if callable(old):
                try:
                    return old(code, data)
                except Exception:
                    return None
            return None
        ordered = [parsed[k] for k in sorted(parsed)][-14:]
        latest = ordered[-1]
        q = feed.q("KR", code)
        q.update_flow(latest["foreign"], latest["institution"], latest["program"])
        q.person_net = latest["person"]
        try:
            from collections import deque
            q.investor_daily = deque(ordered, maxlen=14)
        except Exception:
            q.investor_daily = ordered
        q.investor_asof = latest["date"]
        q.investor_data_ready = True
        q.investor_updated_at = time.time()
        return True

    apply_investor._old = getattr(feed, "_apply_investor", None)
    feed._apply_investor = apply_investor

    def priority_codes():
        fixed = [str(x) for x in list(getattr(feed, "fixed", {}).get("KR", []) or []) if str(x)]
        leaders = []
        candidates = []
        try:
            for x in list((core.CACHE.get("KR") or {}).get("sectors") or [])[:12]:
                c = str(x.get("leader_code") or "")
                if c:
                    leaders.append(c)
            for x in list((core.CACHE.get("KR") or {}).get("scalp") or [])[:30]:
                c = str(x.get("code") or "")
                if c:
                    candidates.append(c)
        except Exception:
            pass
        broad = [str(x) for x in list(getattr(feed, "sector_scan_codes", []) or []) if str(x)]
        return list(dict.fromkeys(leaders + candidates + fixed + broad))

    def investor_loop():
        from nhplug import call
        idx = 0
        while not feed._stop.is_set():
            codes = priority_codes()
            if not codes:
                feed._stop.wait(1.0)
                continue
            code = codes[idx % len(codes)]
            idx += 1
            success = False
            for market_cd in feed._market_order():
                try:
                    data = call(
                        "/krstock/quote/v1/currentInvestor",
                        {"market_cd": market_cd, "iem_cd": code, "array_cnt": "14"},
                    )
                    feed._apply_investor(code, data)
                    feed.investor_updated_at = time.time()
                    success = True
                    break
                except Exception as exc:
                    if "429" in str(exc):
                        feed._stop.wait(2.5)
                        break
            feed._stop.wait(0.7 if success else 1.0)

    feed.investor_loop = investor_loop


def _ai_key(m):
    return f"ai_time_history_v364_{m}"


def _load_ai(core):
    for m in ("KR", "US"):
        try:
            data = core.store.load_json(_ai_key(m), []) or []
            if isinstance(data, list):
                _AI_HISTORY[m] = [dict(x) for x in data if isinstance(x, dict)][-96:]
        except Exception:
            pass


def _record_ai(core, market):
    rows = list((core.CACHE.get(market) or {}).get("scalp") or [])
    if not rows:
        return
    now = _market_now(core, market)
    if market == "KR":
        mins = now.hour * 60 + now.minute
        active = now.weekday() < 5 and 9 * 60 <= mins <= 15 * 60 + 30
    else:
        mins = now.hour * 60 + now.minute
        active = now.weekday() < 5 and 9 * 60 + 30 <= mins <= 16 * 60
    if not active:
        return
    bucket = f"{now.hour:02d}:{(now.minute // 10) * 10:02d}"
    ranked = sorted(rows, key=lambda x: _f(x.get("score")), reverse=True)
    top = ranked[:10]
    item = {
        "time": bucket,
        "score": round(_f(ranked[0].get("score")), 1),
        "name": str(ranked[0].get("name") or ranked[0].get("code") or ""),
        "avg": round(sum(_f(x.get("score")) for x in top) / max(1, len(top)), 1),
        "ready": sum(1 for x in ranked if _f(x.get("score")) >= 75.0),
        "count": len(ranked),
        "ts": time.time(),
    }
    with _AI_LOCK:
        h = [x for x in _AI_HISTORY.get(market, []) if x.get("time") != bucket]
        h.append(item)
        _AI_HISTORY[market] = h[-96:]
        try:
            core.store.save_json(_ai_key(market), _AI_HISTORY[market])
        except Exception:
            pass


def _install_ai_server(core):
    global _AI_THREAD_STARTED
    _load_ai(core)
    app = getattr(core, "app", None)
    if app is not None and not getattr(app.state, "_namuh_ai_time_route", False):
        app.state._namuh_ai_time_route = True

        @app.get("/api/v364/ai-time")
        def ai_time(market: str = "KR"):
            m = "US" if str(market).upper() == "US" else "KR"
            with _AI_LOCK:
                h = [dict(x) for x in _AI_HISTORY.get(m, [])]
            return {"ok": True, "market": m, "history": h[-48:], "source": "server persisted 10m snapshots"}

        @app.get("/api/v364/entry-analysis")
        def entry_analysis(market: str = "KR"):
            m = "US" if str(market).upper() == "US" else "KR"
            rows = list((core.CACHE.get(m) or {}).get("scalp") or [])
            scores = [_f(x.get("score")) for x in rows]
            hard = []
            for x in rows:
                c1 = dict(x.get("condition1") or {})
                g = dict(c1.get("gates") or {})
                if g.get("daily") and g.get("minute1m") and g.get("execution") and g.get("orderbook"):
                    hard.append(x)
            paper = getattr(core, "paper", None)
            trades = list(getattr(paper, "trades", []) or []) if paper is not None else []
            store_status = {}
            try:
                store_status = dict(core.store.status())
            except Exception:
                pass
            return {
                "ok": True, "market": m, "candidate_count": len(rows),
                "score_max": max(scores) if scores else None,
                "score_avg": round(sum(scores) / len(scores), 1) if scores else None,
                "at70": sum(1 for s in scores if s >= 70),
                "at72": sum(1 for s in scores if s >= 72),
                "at75": sum(1 for s in scores if s >= 75),
                "at78": sum(1 for s in scores if s >= 78),
                "hard_gate_count": len(hard),
                "hard_at75": sum(1 for x in hard if _f(x.get("score")) >= 75),
                "trade_count_total": len(trades),
                "trade_count_market": sum(1 for t in trades if str(t.get("market") or "").upper() == m),
                "store": store_status,
            }

    if not _AI_THREAD_STARTED:
        _AI_THREAD_STARTED = True

        def loop():
            while True:
                try:
                    _record_ai(core, "KR")
                    _record_ai(core, "US")
                except Exception:
                    pass
                time.sleep(15)

        threading.Thread(target=loop, daemon=True, name="ai-time-server-history").start()


def _patch_frontend():
    p = ROOT / "static" / "v364_main.js"
    if p.exists():
        text = p.read_text(encoding="utf-8")
        text = text.replace(
            "const S={scores:{KR:[],US:[]},filter:{KR:'ALL',US:'ALL'}};",
            "const S={scores:{KR:[],US:[]},filter:{KR:'ALL',US:'ALL'},ai:{KR:[],US:[]}};"
        )
        text = text.replace(
            "function history(m){try{const a=JSON.parse(localStorage.getItem(hkey(m))||'[]');return Array.isArray(a)?a:[]}catch(_){return []}}",
            "function history(m){const s=S.ai?.[m]||[];if(s.length)return s;try{const a=JSON.parse(localStorage.getItem(hkey(m))||'[]');return Array.isArray(a)?a:[]}catch(_){return []}}"
        )
        if "async function loadAiServer()" not in text:
            helper = "async function loadAiServer(){const m=mode();try{const r=await fetch(`/api/v364/ai-time?market=${m}`,{cache:'no-store'});if(!r.ok)return;const d=await r.json();if(Array.isArray(d.history)){S.ai[m]=d.history;renderTimes()}}catch(_){}}\n"
            text = text.replace("async function loadScores(){", helper + "async function loadScores(){", 1)
        text = text.replace(
            "S.scores[m]=rows;snapshot(m,rows);renderTimes();labelCards(rows,m)",
            "S.scores[m]=rows;snapshot(m,rows);await loadAiServer();renderTimes();labelCards(rows,m)"
        )
        text = text.replace("r.filter(v=>num(v.score)>=72).length", "r.filter(v=>num(v.score)>=75).length")
        text = text.replace("72↑", "75↑")
        text = re.sub(r"setInterval\(loadScores,\s*(?:1000|5000|10000|20000)\)", "setInterval(loadScores,10000)", text)
        old_trade = "function renderTrades(st){ensureTrades();const m=mode(),f=S.filter[m],all=st?.paper?.trades||st?.account?.trades||[],rows=all.filter(t=>tmarket(t)===m&&(f==='ALL'||side(t)===f)).slice(0,100);const title=$('#v364TradeTitle');if(title)title.textContent=m==='US'?'미장 거래내역':'국장 거래내역';const box=$('#v364Trades');if(box)box.innerHTML=rows.map(tradeRow).join('')||'<div class=\"v364-empty\">해당 필터 거래내역 없음</div>';$('#v364Filter')?.querySelectorAll('button').forEach(b=>b.classList.toggle('active',b.dataset.f===f))}"
        new_trade = "let __tradeRenderKey='';function renderTrades(st){ensureTrades();const m=mode(),f=S.filter[m],all=st?.paper?.trades||st?.account?.trades||[],rows=all.filter(t=>tmarket(t)===m&&(f==='ALL'||side(t)===f)).slice(0,100);const title=$('#v364TradeTitle');if(title)title.textContent=m==='US'?'미장 거래내역':'국장 거래내역';const html=rows.map(tradeRow).join('')||'<div class=\"v364-empty\">해당 필터 거래내역 없음</div>',key=m+'|'+f+'|'+html;if(key!==__tradeRenderKey){__tradeRenderKey=key;const box=$('#v364Trades');if(box)box.innerHTML=html}$('#v364Filter')?.querySelectorAll('button').forEach(b=>b.classList.toggle('active',b.dataset.f===f))}"
        text = text.replace(old_trade, new_trade)
        text = text.replace(
            "function init(){ensure();calendarFix();hook();changed();",
            "function init(){ensure();calendarFix();hook();changed();loadAiServer();"
        )
        p.write_text(text, encoding="utf-8")

    p = ROOT / "static" / "app.js"
    if p.exists():
        text = p.read_text(encoding="utf-8")
        text = re.sub(r"setInterval\(refresh,\s*(?:1000|3000|5000|10000)\)", "setInterval(refresh,5000)", text)
        text = text.replace(
            "render(x.state);",
            "const __s=JSON.parse(JSON.stringify(x.state));if(__s?.paper)__s.paper.trades=[];render(__s);"
        )
        p.write_text(text, encoding="utf-8")

    p = ROOT / "static" / "coin.js"
    if p.exists():
        text = p.read_text(encoding="utf-8")
        text = re.sub(r"setInterval\(refresh,\s*(?:1000|3000|5000|10000)\)", "setInterval(refresh,5000)", text)
        p.write_text(text, encoding="utf-8")


def _install_health(core):
    old = getattr(core, "health_payload", None)
    if not callable(old):
        return

    def health():
        d = dict(old())
        try:
            qs = list(core.feed.quotes_for("KR").values())
            ready = sum(1 for q in qs if bool(getattr(q, "investor_data_ready", False)))
        except Exception:
            ready = 0
            qs = []
        d["final_runtime_0908"] = {
            "active": True,
            "investor_ready": ready,
            "investor_quotes": len(qs),
            "ai_history": {m: len(_AI_HISTORY.get(m, [])) for m in ("KR", "US")},
            "state_poll_sec": 5,
            "ai_poll_sec": 10,
            "coin_poll_sec": 5,
            "daily_score": "pass=10 fail=1 authoritative",
        }
        return d

    core.health_payload = health


def apply(ns=None):
    global _INSTALLED
    if _INSTALLED:
        return True
    core = ns.get("core") if isinstance(ns, dict) else None
    if core is None:
        return False
    _install_daily_fix(core)
    _install_investor_priority(core)
    _install_ai_server(core)
    _patch_frontend()
    _install_health(core)
    _INSTALLED = True
    print("NAMUH FINAL RUNTIME 0908 active: investor priority + daily authoritative + server AI history + no trade flicker + sane polling", flush=True)
    return True
