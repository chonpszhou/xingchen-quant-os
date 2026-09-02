"""单标的 SMA 金叉/死叉 策略（接入新引擎接口，供研究驱动扫描 / 参数寻优）

对标 paddy-quant-workbench 的 sma_cross：快线站上慢线持仓，否则空仓（t+1 执行）。
单资产版：self._target 在 fast>slow 时为 {symbol: 1.0}，否则 {}。
被 engine.optimizer.optimize 用于「研究驱动全宇宙扫描」逐标的五道闸门验证。
"""
from __future__ import annotations

import pandas as pd

from engine.strategy import Strategy, register


@register
class SMACrossStrategy(Strategy):
    name = "sma_cross"
    params = {"symbol": "", "market": "a", "fast": 5, "slow": 20}

    def on_init(self):
        self._symbol = self.params.get("symbol") or ""
        self._market = self.params.get("market") or "a"
        self._fast = int(self.params.get("fast", 5))
        self._slow = int(self.params.get("slow", 20))
        self._target = {}
        self.i = 0
        # 预计算目标权重序列（按日期），on_bar 仅查表
        self._target_series: dict = {}
        if self._symbol and self.ds is not None:
            df = self.ds.bars(self._market, self._symbol)
            if df is not None and "close" in df.columns and len(df):
                close = df.set_index("date")["close"].sort_index()
                fast = close.rolling(self._fast).mean()
                slow = close.rolling(self._slow).mean()
                sig = (fast > slow).fillna(False)
                self._target_series = {
                    dt: {self._symbol: 1.0} if s else {}
                    for dt, s in sig.items()
                }

    def on_bar(self, symbol, bar):
        self._target = self._target_series.get(bar.datetime, {})
        return
