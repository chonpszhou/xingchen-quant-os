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
