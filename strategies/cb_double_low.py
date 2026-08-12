"""可转债双低策略（TOP20 等权 + 信用过滤，接入新引擎接口）"""

from __future__ import annotations

from engine.strategy import Strategy, register


@register
class CBDoubleLowStrategy(Strategy):
    name = "cb_double_low"
    params = {"n_hold": 20, "rebalance": 20}

    def on_init(self):
        self._target = {}
        self.i = 0

    def on_bar(self, symbol, bar):
        if self.i % self.params["rebalance"] != 0:
            return
        if bar.datetime is None:
            return
        w = self.ds.cb_target(str(bar.datetime.date()))
        if w:
            # 归一化为等权前 n_hold
            n = min(self.params["n_hold"], len(w))
            self._target = {k: 1.0 / n for k in list(w)[:n]}
