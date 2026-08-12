"""双动量策略（迁移自 research_dual_momentum，接入新引擎接口）"""

from __future__ import annotations

import numpy as np
import pandas as pd

from engine.strategy import Strategy, register


@register
class DualMomentumStrategy(Strategy):
    name = "dual_momentum"
    params = {"assets": ["SPY", "GLD", "DBC"], "safe": "TLT",
              "lookbacks": (63, 126, 252), "rebalance": 21}

    def on_init(self):
        self._close = self.ds.closes("美股", self.params["assets"] + [self.params["safe"]])
        self._mom = pd.DataFrame(index=self._close.index)
        for a in self.params["assets"]:
            self._mom[a] = np.mean(
                [(self._close[a] / self._close[a].shift(L) - 1).values
                 for L in self.params["lookbacks"]], axis=0)
        self._target = {}
        self.i = 0

    def on_bar(self, symbol, bar):
        if self.i % self.params["rebalance"] != 0:
            return
        row = self._mom.loc[bar.datetime] if bar.datetime in self._mom.index else self._mom.iloc[-1]
        best = row.dropna()
        if best.empty:
            return
        pick = best.idxmax()
        target = {pick: 1.0} if best[pick] > 0 else {self.params["safe"]: 1.0}
        self._target = target
        return
