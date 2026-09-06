from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from contextlib import contextmanager


class StateStore:
    """Small persistence layer.

    Render Postgres is used when DATABASE_URL is present. Local/dev fallback is
    SQLite so the app still boots without external infrastructure. The fallback
    is intentionally reported as non-durable on Render.
    """

    def __init__(self):
        self.database_url = os.getenv("DATABASE_URL", "").strip()
        self.sqlite_path = os.getenv("GY_STATE_PATH", "/tmp/gy_state.sqlite3").strip() or "/tmp/gy_state.sqlite3"
        self.mode = "postgres" if self.database_url.startswith(("postgres://", "postgresql://")) else "sqlite"
        self.lock = threading.RLock()
        self.last_error = ""
        self._init_schema()

    @contextmanager
    def _conn(self):
        if self.mode == "postgres":
            import psycopg
            conn = psycopg.connect(self.database_url, autocommit=True)
        else:
            conn = sqlite3.connect(self.sqlite_path, timeout=10)
        try:
            yield conn
            if self.mode == "sqlite":
                conn.commit()
        finally:
            conn.close()

    def _init_schema(self):
        try:
            with self._conn() as conn:
                cur = conn.cursor()
                cur.execute(
                    "CREATE TABLE IF NOT EXISTS gy_kv ("
                    "k TEXT PRIMARY KEY, v TEXT NOT NULL, updated_at DOUBLE PRECISION NOT NULL)"
                )
                if self.mode == "postgres":
                    cur.execute(
                        "CREATE TABLE IF NOT EXISTS gy_signals ("
                        "id BIGSERIAL PRIMARY KEY, dedupe_key TEXT UNIQUE NOT NULL, "
                        "ts DOUBLE PRECISION NOT NULL, market TEXT NOT NULL, strategy TEXT NOT NULL, "
                        "code TEXT NOT NULL, payload TEXT NOT NULL)"
                    )
                else:
                    cur.execute(
                        "CREATE TABLE IF NOT EXISTS gy_signals ("
                        "id INTEGER PRIMARY KEY AUTOINCREMENT, dedupe_key TEXT UNIQUE NOT NULL, "
                        "ts REAL NOT NULL, market TEXT NOT NULL, strategy TEXT NOT NULL, "
                        "code TEXT NOT NULL, payload TEXT NOT NULL)"
                    )
                cur.execute("CREATE INDEX IF NOT EXISTS gy_signals_ts_idx ON gy_signals(ts)")
                # Exact same-clock 1-minute volume history for the KR abnormal-flow
                # baseline.  One compact row per stock/minute/session; works on both
                # Render Postgres and the Oracle/SQLite fallback.
                cur.execute(
                    "CREATE TABLE IF NOT EXISTS gy_minute_volume ("
                    "market TEXT NOT NULL, code TEXT NOT NULL, trade_date TEXT NOT NULL, "
                    "minute TEXT NOT NULL, volume DOUBLE PRECISION NOT NULL, "
                    "updated_at DOUBLE PRECISION NOT NULL, "
                    "PRIMARY KEY(market,code,trade_date,minute))"
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS gy_minute_volume_lookup_idx "
                    "ON gy_minute_volume(market,code,minute,trade_date)"
                )
                cur.close()
            self.last_error = ""
        except Exception as exc:
            self.last_error = str(exc)[:300]

    def save_json(self, key, payload):
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        now = time.time()
        try:
            with self.lock, self._conn() as conn:
                cur = conn.cursor()
                if self.mode == "postgres":
                    cur.execute(
                        "INSERT INTO gy_kv(k,v,updated_at) VALUES(%s,%s,%s) "
                        "ON CONFLICT(k) DO UPDATE SET v=EXCLUDED.v,updated_at=EXCLUDED.updated_at",
                        (key, raw, now),
                    )
                else:
                    cur.execute(
                        "INSERT INTO gy_kv(k,v,updated_at) VALUES(?,?,?) "
                        "ON CONFLICT(k) DO UPDATE SET v=excluded.v,updated_at=excluded.updated_at",
                        (key, raw, now),
                    )
                cur.close()
            self.last_error = ""
            return True
        except Exception as exc:
            self.last_error = str(exc)[:300]
            return False

    def load_json(self, key, default=None):
        try:
            with self.lock, self._conn() as conn:
                cur = conn.cursor()
                cur.execute("SELECT v FROM gy_kv WHERE k=%s" if self.mode == "postgres" else "SELECT v FROM gy_kv WHERE k=?", (key,))
                row = cur.fetchone()
                cur.close()
            self.last_error = ""
            return json.loads(row[0]) if row else default
        except Exception as exc:
            self.last_error = str(exc)[:300]
            return default

    def record_signal(self, dedupe_key, market, strategy, code, payload, ts=None):
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        ts = float(ts or time.time())
        try:
            with self.lock, self._conn() as conn:
                cur = conn.cursor()
                if self.mode == "postgres":
                    cur.execute(
                        "INSERT INTO gy_signals(dedupe_key,ts,market,strategy,code,payload) "
                        "VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT(dedupe_key) DO NOTHING",
                        (dedupe_key, ts, market, strategy, code, raw),
                    )
                else:
                    cur.execute(
                        "INSERT OR IGNORE INTO gy_signals(dedupe_key,ts,market,strategy,code,payload) VALUES(?,?,?,?,?,?)",
                        (dedupe_key, ts, market, strategy, code, raw),
                    )
                cur.close()
            self.last_error = ""
            return True
        except Exception as exc:
            self.last_error = str(exc)[:300]
            return False

    def save_minute_volume(self, market, code, trade_date, minute, volume):
        market = str(market or "KR").upper()
        code = str(code or "").upper().strip()
        trade_date = str(trade_date or "").strip()
        minute = str(minute or "").strip()
        try:
            volume = float(volume or 0)
        except Exception:
            volume = 0.0
        if not code or len(trade_date) != 10 or len(minute) != 5 or volume < 0:
            return False
        now = time.time()
        try:
            with self.lock, self._conn() as conn:
                cur = conn.cursor()
                if self.mode == "postgres":
                    cur.execute(
                        "INSERT INTO gy_minute_volume(market,code,trade_date,minute,volume,updated_at) "
                        "VALUES(%s,%s,%s,%s,%s,%s) "
                        "ON CONFLICT(market,code,trade_date,minute) DO UPDATE SET "
                        "volume=EXCLUDED.volume,updated_at=EXCLUDED.updated_at",
                        (market, code, trade_date, minute, volume, now),
                    )
                else:
                    cur.execute(
                        "INSERT INTO gy_minute_volume(market,code,trade_date,minute,volume,updated_at) "
                        "VALUES(?,?,?,?,?,?) "
                        "ON CONFLICT(market,code,trade_date,minute) DO UPDATE SET "
                        "volume=excluded.volume,updated_at=excluded.updated_at",
                        (market, code, trade_date, minute, volume, now),
                    )
                cur.close()
            self.last_error = ""
            return True
        except Exception as exc:
            self.last_error = str(exc)[:300]
            return False

    def minute_volume_baseline(self, market, code, minute, before_date, sessions=5):
        market = str(market or "KR").upper()
        code = str(code or "").upper().strip()
        minute = str(minute or "").strip()
        before_date = str(before_date or "").strip()
        sessions = max(1, min(20, int(sessions or 5)))
        if not code or len(minute) != 5 or len(before_date) != 10:
            return {"count": 0, "average": 0.0, "dates": [], "volumes": []}
        try:
            with self.lock, self._conn() as conn:
                cur = conn.cursor()
                sql = (
                    "SELECT trade_date,volume FROM gy_minute_volume "
                    "WHERE market=%s AND code=%s AND minute=%s AND trade_date<%s "
                    "ORDER BY trade_date DESC LIMIT %s"
                    if self.mode == "postgres" else
                    "SELECT trade_date,volume FROM gy_minute_volume "
                    "WHERE market=? AND code=? AND minute=? AND trade_date<? "
                    "ORDER BY trade_date DESC LIMIT ?"
                )
                cur.execute(sql, (market, code, minute, before_date, sessions))
                rows = cur.fetchall()
                cur.close()
            vals = [(str(d), float(v or 0)) for d, v in rows if float(v or 0) >= 0]
            vols = [v for _, v in vals]
            avg = sum(vols) / len(vols) if vols else 0.0
            self.last_error = ""
            return {
                "count": len(vols),
                "average": avg,
                "dates": [d for d, _ in vals],
                "volumes": vols,
            }
        except Exception as exc:
            self.last_error = str(exc)[:300]
            return {"count": 0, "average": 0.0, "dates": [], "volumes": []}

    def minute_volume_for_dates(self, market, code, minute, dates):
        market = str(market or "KR").upper()
        code = str(code or "").upper().strip()
        minute = str(minute or "").strip()
        clean_dates = []
        for d in dates or []:
            d = str(d or "").strip()
            if len(d) == 10 and d not in clean_dates:
                clean_dates.append(d)
        clean_dates = clean_dates[-10:]
        if not code or len(minute) != 5 or not clean_dates:
            return {"count": 0, "average": 0.0, "dates": [], "volumes": [], "missing_dates": clean_dates}
        try:
            with self.lock, self._conn() as conn:
                cur = conn.cursor()
                marks = ",".join(["%s"] * len(clean_dates)) if self.mode == "postgres" else ",".join(["?"] * len(clean_dates))
                sql = (
                    f"SELECT trade_date,volume FROM gy_minute_volume "
                    f"WHERE market={'%s' if self.mode == 'postgres' else '?'} "
                    f"AND code={'%s' if self.mode == 'postgres' else '?'} "
                    f"AND minute={'%s' if self.mode == 'postgres' else '?'} "
                    f"AND trade_date IN ({marks}) ORDER BY trade_date ASC"
                )
                cur.execute(sql, (market, code, minute, *clean_dates))
                rows = cur.fetchall()
                cur.close()
            by_date = {str(d): float(v or 0) for d, v in rows if float(v or 0) >= 0}
            found_dates = [d for d in clean_dates if d in by_date]
            vols = [by_date[d] for d in found_dates]
            missing = [d for d in clean_dates if d not in by_date]
            avg = sum(vols) / len(vols) if vols else 0.0
            self.last_error = ""
            return {
                "count": len(vols), "average": avg, "dates": found_dates,
                "volumes": vols, "missing_dates": missing,
            }
        except Exception as exc:
            self.last_error = str(exc)[:300]
            return {"count": 0, "average": 0.0, "dates": [], "volumes": [], "missing_dates": clean_dates}

    def prune_minute_volume(self, before_date):
        before_date = str(before_date or "").strip()
        if len(before_date) != 10:
            return 0
        try:
            with self.lock, self._conn() as conn:
                cur = conn.cursor()
                cur.execute(
                    "DELETE FROM gy_minute_volume WHERE trade_date<%s"
                    if self.mode == "postgres" else
                    "DELETE FROM gy_minute_volume WHERE trade_date<?",
                    (before_date,),
                )
                n = int(cur.rowcount or 0)
                cur.close()
            self.last_error = ""
            return n
        except Exception as exc:
            self.last_error = str(exc)[:300]
            return 0

    def recent_signal_count(self, days=30):
        cutoff = time.time() - max(1, int(days)) * 86400
        try:
            with self.lock, self._conn() as conn:
                cur = conn.cursor()
                cur.execute(
                    "SELECT COUNT(*) FROM gy_signals WHERE ts>=%s" if self.mode == "postgres" else "SELECT COUNT(*) FROM gy_signals WHERE ts>=?",
                    (cutoff,),
                )
                n = int(cur.fetchone()[0])
                cur.close()
            return n
        except Exception as exc:
            self.last_error = str(exc)[:300]
            return 0

    def status(self):
        return {
            "mode": self.mode,
            "durable": self.mode == "postgres",
            "configured": self.mode == "postgres" or bool(self.sqlite_path),
            "error": self.last_error,
        }
