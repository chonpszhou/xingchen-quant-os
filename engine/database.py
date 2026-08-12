"""交易/净值持久化（对标 freqtrade persistence，SQLite）"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd


class Database:
    def __init__(self, db_path: str | Path):
        self.conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self.conn.executescript("""
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            strategy TEXT, date TEXT, symbol TEXT, direction TEXT,
            price REAL, value REAL, cost REAL
        );
        CREATE TABLE IF NOT EXISTS nav (
            strategy TEXT, date TEXT, nav REAL,
            PRIMARY KEY (strategy, date)
        );
        CREATE TABLE IF NOT EXISTS positions (
            strategy TEXT, symbol TEXT, shares REAL, last_price REAL,
            PRIMARY KEY (strategy, symbol)
        );
        """)
        self.conn.commit()

    def record_trade(self, strategy, date, symbol, direction, price, value, cost):
        self.conn.execute(
            "INSERT INTO trades (strategy,date,symbol,direction,price,value,cost) VALUES (?,?,?,?,?,?,?)",
            (strategy, str(date), symbol, direction, float(price), float(value), float(cost)))
        self.conn.commit()

    def record_nav(self, strategy, date, nav):
        self.conn.execute(
            "INSERT OR REPLACE INTO nav (strategy,date,nav) VALUES (?,?,?)",
            (strategy, str(date), float(nav)))
        self.conn.commit()

    def save_positions(self, strategy, positions, prices):
        self.conn.execute("DELETE FROM positions WHERE strategy=?", (strategy,))
        for sym, sh in positions.items():
            self.conn.execute(
                "INSERT INTO positions (strategy,symbol,shares,last_price) VALUES (?,?,?,?)",
                (strategy, sym, float(sh), float(prices.get(sym, 0.0))))
        self.conn.commit()

    def trades(self, strategy=None) -> pd.DataFrame:
        q = "SELECT * FROM trades" + (" WHERE strategy=?" if strategy else "")
        return pd.read_sql_query(q, self.conn, params=(strategy,) if strategy else None)

    def nav_series(self, strategy=None) -> pd.DataFrame:
        q = "SELECT strategy,date,nav FROM nav" + (" WHERE strategy=?" if strategy else "")
        df = pd.read_sql_query(q, self.conn, params=(strategy,) if strategy else None)
        if not df.empty:
            df["date"] = pd.to_datetime(df["date"])
            df = df.sort_values("date")
        return df
