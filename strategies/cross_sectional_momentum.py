"""横截面动量（M-938）：同市场内按 12-1 动量做横截面 z-score 排序，前 top_q 分位做多本标的。

对应学习报告主题「横截面因子」：剥离市场 beta，用行业内/市场内相对强度而非绝对动量，
规避时序动量易被短期反转与过拟合拖累的边界。逐标的过五道闸（与其他策略同纪律）。
"""
from __future__ import annotations

import pandas as pd

from engine.strategy import Strategy, register
from engine.cross_sectional import build_panel, cs_zscore, in_top_quantile


@register
class CrossSectionalMomentumStrategy(Strategy):
    name = "cs_momentum"
    params = {"symbol": "", "market": "a", "lookback": 252, "top_q": 0.3}

    def on_init(self):
        self._symbol = self.params.get("symbol") or ""
        self._market = self.params.get("market") or "a"
        self._lookback = int(self.params.get("lookback", 252))
        self._top_q = float(self.params.get("top_q", 0.3))
        self._target = {}
        self._target_series = {}
        if self._symbol and self.ds is not None:
            panel = build_panel(self.ds, self._market, self._symbol)
            if self._symbol in panel.columns and len(panel) >= self._lookback + 2:
                mom = panel / panel.shift(self._lookback) - 1.0
                z = cs_zscore(mom)
                long_sig = in_top_quantile(z, self._symbol, self._top_q).fillna(False)
                self._target_series = {
                    dt: {self._symbol: 1.0} if s else {}
                    for dt, s in long_sig.items()
                }

    def on_bar(self, symbol, bar):
        self._target = self._target_series.get(bar.datetime, {})
        return
