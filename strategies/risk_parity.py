"""风险平价策略（逆波动率，接入新引擎接口）"""

from __future__ import annotations

import numpy as np

from engine.strategy import Strategy, register


@register
class RiskParityStrategy(Strategy):
    name = "risk_parity"
    params = {"assets": ["SPY", "GLD", "TLT", "DBC"], "target_vol": 0.08,
              "rebalance": 21}

    def on_init(self):
        self._close = self.ds.closes("美股", self.params["assets"])
        self._vol = self._close.pct_change().rolling(20).std() * np.sqrt(252)
        self._target = {}
        self.i = 0

    def on_bar(self, symbol, bar):
        if self.i % self.params["rebalance"] != 0:
            return
        if bar.datetime not in self._vol.index:
            return
        v = self._vol.loc[bar.datetime]
        w = 1.0 / v.clip(lower=1e-4)
        w = w / w.sum()
        pv = np.sqrt(w.values @ np.diag(v.fillna(1e-4).values ** 2) @ w.values)
        w = w * min(1.0, self.params["target_vol"] / max(pv, 1e-4))
        self._target = w.fillna(0.0).to_dict()
