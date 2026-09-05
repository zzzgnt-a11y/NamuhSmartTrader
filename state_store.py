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

