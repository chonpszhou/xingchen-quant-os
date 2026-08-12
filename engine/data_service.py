"""统一数据服务（封装 datahub，供策略/回测使用；对标 freqtrade data）"""

from __future__ import annotations

from pathlib import Path

import pandas as pd


class DataService:
    def __init__(self, data_dir: str | Path):
        from datahub.store import LocalStore
        self.store = LocalStore(str(data_dir))

    def bars(self, market: str, symbol: str) -> pd.DataFrame | None:
        return self.store.load_bars(market, symbol)

    def closes(self, market: str, symbols: list[str]) -> pd.DataFrame:
        out = {}
        for s in symbols:
            df = self.store.load_bars(market, s)
            if df is not None:
                out[s] = df.set_index("date")["close"]
        return pd.DataFrame(out).sort_index()

    def status(self) -> pd.DataFrame:
        return self.store.all_status()

    # ---- 可转债（双低策略数据） ----

    def cb_panel(self) -> pd.DataFrame:
        p = Path(self.store.root) / "cb_panel.parquet"
        return pd.read_parquet(p) if p.exists() else pd.DataFrame()

    def cb_close(self) -> pd.DataFrame:
        """可转债收盘价宽表（numpy 构建，兼容 pandas 2.x）"""
        df = self.cb_panel()
        if df.empty:
            return pd.DataFrame()
        df = df[df["bond"].str.startswith(("110", "111", "113", "118", "123", "127", "128"))]
        df["date"] = pd.to_datetime(df["date"])
        df = df[df["close"].notna()]
        dates = pd.DatetimeIndex(sorted(df["date"].unique()))
        bonds = sorted(df["bond"].unique())
        di = {d: i for i, d in enumerate(dates)}
        ci = {b: j for j, b in enumerate(bonds)}
        import numpy as np
        rows = np.array([di[d] for d in df["date"]])
        cols = np.array([ci[b] for b in df["bond"]])
        m = np.full((len(dates), len(bonds)), np.nan)
        m[rows, cols] = df["close"].values
        return pd.DataFrame(m, index=dates, columns=bonds)

    def cb_target(self, as_of) -> dict[str, float]:
        """双低目标：TOP20 等权（信用过滤），返回 {bond: 1/20}"""
        panel = self.cb_panel()
        meta_p = Path(self.store.root) / "cb_meta.parquet"
        if panel.empty or not meta_p.exists():
            return {}
        meta = pd.read_parquet(meta_p)
        meta["code"] = meta["code"].astype(str).str.zfill(6)
        meta["rating"] = meta["rating"].astype(str)
        panel["date"] = pd.to_datetime(panel["date"])
        panel = panel[panel["date"] <= pd.Timestamp(as_of)]
        panel = panel[panel["bond"].str.startswith(("110", "111", "113", "118", "123", "127", "128"))]
        if panel.empty:
            return {}
        latest = panel.loc[panel.groupby("bond")["date"].idxmax()]
        ms = meta[["code", "stock_name", "rating"]].rename(columns={"code": "mc"})
        latest = latest.merge(ms, left_on="bond", right_on="mc").drop(columns=["mc"])
        bad = latest["stock_name"].astype(str).str.contains("ST") | latest["rating"].str.startswith("C") \
            | latest["rating"].isna()
        latest = latest[~bad]
        latest = latest[(latest["close"] <= 130) & (latest["premium_pct"] <= 50)]
        if latest.empty:
            return {}
        latest["score"] = latest["close"] + latest["premium_pct"]
        top = latest.nsmallest(20, "score")
        return {r["bond"]: 1.0 / len(top) for _, r in top.iterrows()}
