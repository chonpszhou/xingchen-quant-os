"""横截面 ML 因子（M-937）：walk-forward 线性回归预测下期截面收益，前 top_q 分位做多。

对应学习报告主题「ML-powered cross-sectional return prediction (7 factors)」。
纯 numpy 实现（镜像无 sklearn 环境），特征=多周期动量+波动+短期反转，标签=未来 21 日收益；
周期性再训练、训练只用历史，严格无前视。逐标的过五道闸（与其他策略同纪律）。
"""
from __future__ import annotations

import pandas as pd

from engine.strategy import Strategy, register
from engine.cross_sectional import build_panel, walk_forward_ml_scores, in_top_quantile


@register
class MLFactorStrategy(Strategy):
    name = "ml_factor"
    params = {"symbol": "", "market": "a", "top_q": 0.1, "refit": 63, "fwd": 21}

    def on_init(self):
        self._symbol = self.params.get("symbol") or ""
        self._market = self.params.get("market") or "a"
        self._top_q = float(self.params.get("top_q", 0.1))
        self._refit = int(self.params.get("refit", 63))
        self._fwd = int(self.params.get("fwd", 21))
        self._target = {}
        self._target_series = {}
        if self._symbol and self.ds is not None:
            panel = build_panel(self.ds, self._market, self._symbol)
            if self._symbol in panel.columns and len(panel) >= 520:
                scores = walk_forward_ml_scores(panel, refit=self._refit, fwd=self._fwd)
                long_sig = in_top_quantile(scores, self._symbol, self._top_q).fillna(False)
                self._target_series = {
                    dt: {self._symbol: 1.0} if s else {}
                    for dt, s in long_sig.items()
                }

    def on_bar(self, symbol, bar):
        self._target = self._target_series.get(bar.datetime, {})
        return
