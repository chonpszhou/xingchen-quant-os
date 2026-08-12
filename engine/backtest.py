"""回测引擎：同一 Strategy 接口跑历史（对标 vnpy BacktestingEngine）"""

from __future__ import annotations

import pandas as pd

from .object import BarData


class BacktestEngine:
    def __init__(self, strategy, executor, risk=None, rebalance_every: int = 1):
        self.strategy = strategy
        self.executor = executor
        self.risk = risk
        self.rebalance_every = rebalance_every
        self.i = 0

    def run(self, close: pd.DataFrame):
        rets = close.pct_change()
        nav_series = {}
        last_weights = {}
        for i, (dt, row) in enumerate(close.iterrows()):
            self.i = i
            prices = row.dropna().to_dict()
            self.strategy.on_bar(None, BarData(symbol="", datetime=dt, close_price=0.0))
            weights = getattr(self.strategy, "_target", {})
            if weights and self.risk:
                ok, msg = self.risk.pre_trade(weights, self.executor.nav(prices))
                if not ok:
                    weights = {}
            if weights != last_weights:
                self.executor.execute(weights, prices, dt)
                last_weights = weights
            nav_series[dt] = self.executor.nav(prices)
        return pd.Series(nav_series)
