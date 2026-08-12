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

    def run(self, close: pd.DataFrame, start=None, end=None, record_nav=True):
        """按 close 逐根 K 线回测；t+1 执行（信号于 T 日收盘，T+1 收盘价成交）"""
        rets = close.pct_change()
        if start is not None:
            close = close[close.index >= pd.Timestamp(start)]
        if end is not None:
            close = close[close.index <= pd.Timestamp(end)]
        nav_series = {}
        pending = {}
        last_exec = {}
        rows = list(close.iterrows())
        for i, (dt, row) in enumerate(rows):
            self.i = i
            prices = row.dropna().to_dict()
            # 先执行昨日信号（t+1 收盘价）
            if pending:
                if self.risk:
                    ok, msg = self.risk.pre_trade(pending, self.executor.nav(prices))
                    if not ok:
                        pending = {}
                if pending and pending != last_exec:
                    self.executor.execute(pending, prices, dt)
                    last_exec = pending
                pending = {}
            # 今日信号 → 明日执行
            self.strategy.on_bar(None, BarData(symbol="", datetime=dt, close_price=0.0))
            target = dict(getattr(self.strategy, "_target", {}))
            if target != last_exec:
                pending = target
            if record_nav:
                nav_series[dt] = self.executor.nav(prices)
        if pending:  # 末尾信号也执行一次（收盘价）
            self.executor.execute(pending, rows[-1][1].dropna().to_dict(), rows[-1][0])
        return pd.Series(nav_series)
