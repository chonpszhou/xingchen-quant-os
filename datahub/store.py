"""本地存储：SQLite 元数据 + parquet 日线，支持增量更新与去重"""

from __future__ import annotations

import datetime as dt
import sqlite3
import threading
from pathlib import Path

import pandas as pd

BAR_COLUMNS = ["date", "open", "high", "low", "close", "volume"]
OPTIONAL_COLUMNS = ["amount", "source"]


def _safe_name(symbol: str) -> str:
    return symbol.replace("/", "_").replace("\\", "_").replace(":", "_")


class LocalStore:
    def __init__(self, data_dir: str = "data"):
        self.root = Path(data_dir)
        self.bars_root = self.root / "bars"
        self.bars_root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.root / "meta.db"), check_same_thread=False)
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sync_status (
                market TEXT NOT NULL,
                symbol TEXT NOT NULL,
                last_date TEXT,
                source TEXT,
                updated_at TEXT,
                note TEXT,
                PRIMARY KEY (market, symbol)
            )
            """
        )
        self._conn.commit()

    # ---------- 元数据 ----------

    def status(self, market: str, symbol: str):
        with self._lock:
            cur = self._conn.execute(
                "SELECT last_date, source, updated_at, note FROM sync_status WHERE market=? AND symbol=?",
                (market, symbol),
            )
            row = cur.fetchone()
        if not row:
            return None
        return {"last_date": row[0], "source": row[1], "updated_at": row[2], "note": row[3]}

    def set_status(self, market: str, symbol: str, last_date, source: str, note: str = ""):
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO sync_status (market, symbol, last_date, source, updated_at, note)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(market, symbol) DO UPDATE SET
                    last_date=excluded.last_date, source=excluded.source,
                    updated_at=excluded.updated_at, note=excluded.note
                """,
                (market, symbol, str(last_date), source,
                 dt.datetime.now().isoformat(timespec="seconds"), note[:300]),
            )
            self._conn.commit()

    def all_status(self) -> pd.DataFrame:
        with self._lock:
            return pd.read_sql_query(
                "SELECT market, symbol, last_date, source, updated_at, note FROM sync_status ORDER BY market, symbol",
                self._conn,
            )

    # ---------- 日线 ----------

    def bars_path(self, market: str, symbol: str) -> Path:
        return self.bars_root / market / f"{_safe_name(symbol)}.parquet"

    def load_bars(self, market: str, symbol: str):
        p = self.bars_path(market, symbol)
        if not p.exists():
            return None
        df = pd.read_parquet(p)
        df["date"] = pd.to_datetime(df["date"])
        return df.sort_values("date").reset_index(drop=True)

    def save_bars(self, market: str, symbol: str, df: pd.DataFrame):
        """按 date 去重合并后写入 parquet"""
        if df is None or df.empty:
            return
        keep = BAR_COLUMNS + [c for c in OPTIONAL_COLUMNS if c in df.columns]
        df = df[keep].copy()
        df["date"] = pd.to_datetime(df["date"])
        for c in BAR_COLUMNS[1:]:
            df[c] = pd.to_numeric(df[c], errors="coerce")
        old = self.load_bars(market, symbol)
        if old is not None:
            df = pd.concat([old, df], ignore_index=True)
        df = df.drop_duplicates(subset="date", keep="last").sort_values("date").reset_index(drop=True)
        p = self.bars_path(market, symbol)
        p.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(p, index=False)

    def incremental_start(self, market: str, symbol: str, lookback_days: int, force: bool = False):
        if not force:
            st = self.status(market, symbol)
            if st and st["last_date"]:
                return (dt.date.fromisoformat(st["last_date"]) + dt.timedelta(days=1)).isoformat()
        return (dt.date.today() - dt.timedelta(days=lookback_days)).isoformat()
